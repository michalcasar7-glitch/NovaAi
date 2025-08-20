# -*- coding: utf-8 -*-
import tkinter as tk
from tkinter import scrolledtext
import socket, threading, json, time, os, sys, subprocess
from datetime import datetime
from typing import Optional, Dict, Any

class SimpleMessage:
    def __init__(self, agent_id: str, content: Any, direction: str, msg_type: str = "chat", msg_id: Optional[str] = None, metadata: Optional[Dict[str, Any]] = None): self.agent_id, self.content, self.direction, self.timestamp, self.msg_id, self.metadata = agent_id, content, direction, datetime.now().isoformat(), msg_id, metadata or {}; self.metadata['type'] = msg_type
    def to_json(self) -> str: return json.dumps(self.__dict__, ensure_ascii=False)
    @classmethod
    def from_json(cls, json_str: str) -> 'SimpleMessage': return cls.from_dict(json.loads(json_str))
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'SimpleMessage': return cls(agent_id=data.get('agent_id'), content=data.get('content'), direction=data.get('direction'), msg_type=data.get('metadata', {}).get('type', 'chat'), msg_id=data.get('msg_id'), metadata=data.get('metadata'))

class RelayBridge:
    def __init__(self, port=9999): self.port, self.server_socket, self.client_socket = port, None, None; self.connected, self.running, self.callbacks = False, False, []
    def start_server(self, on_ready_callback):
        try:
            self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM); self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1); self.server_socket.bind(('localhost', self.port)); self.server_socket.listen(1); self.running = True; threading.Thread(target=self._accept_connections, daemon=True).start(); on_ready_callback(f"🌉 RelayBridge server běží na portu {self.port}")
        except Exception as e: on_ready_callback(f"❌ Chyba startu Bridge serveru: {e}")
    def _accept_connections(self):
        while self.running:
            try:
                client_socket, addr = self.server_socket.accept()
                if self.client_socket: self.client_socket.close()
                self.client_socket, self.connected = client_socket, True; [callback('connect', f"📡 GUI připojeno z {addr}") for callback in self.callbacks]; threading.Thread(target=self._listen_client, daemon=True).start()
            except Exception: break
        self.connected = False; [callback('disconnect', "📡 GUI odpojeno.") for callback in self.callbacks]
    def _listen_client(self):
        buffer = ""
        while self.running and self.connected:
            try:
                data = self.client_socket.recv(4096).decode('utf-8');
                if not data: break
                buffer += data;
                while '\n' in buffer:
                    line, buffer = buffer.split('\n', 1); [callback('message', SimpleMessage.from_json(line)) for callback in self.callbacks if line.strip()]
            except Exception: break
        self.connected = False; [callback('disconnect', "📡 GUI odpojeno.") for callback in self.callbacks]
    def send_to_gui(self, message: SimpleMessage):
        if not self.connected: return False
        try: self.client_socket.sendall((message.to_json() + '\n').encode('utf-8')); return True
        except: self.connected = False; return False
    def add_callback(self, callback): self.callbacks.append(callback) if callback not in self.callbacks else None
    def stop(self): self.running = False; self.client_socket.close() if self.client_socket else None; self.server_socket.close() if self.server_socket else None

class RelayManager:
    def __init__(self, bridge_port=9999):
        self.bridge = RelayBridge(port=bridge_port); self.active_relays = {}; self.root = tk.Tk(); self._init_gui()
    def _init_gui(self):
        self.root.title("🔗 External Relay Manager (Selenium)"); self.root.geometry("600x400")
        self.log_view = scrolledtext.ScrolledText(self.root, height=15, bg="#1e1e1e", fg="#d4d4d4", wrap="word"); self.log_view.pack(fill="both", expand=True, padx=10, pady=10)
        self.root.protocol("WM_DELETE_WINDOW", self.stop)
    def start(self):
        self._log("Orchestrátor se spouští v Selenium módu..."); self.bridge.add_callback(self.handle_bridge_event); self.bridge.start_server(on_ready_callback=self._log); self.root.after(5000, self.broadcast_status); self.root.mainloop()

    def _launch_agent(self, agent_id, url):
        if agent_id in self.active_relays and self.active_relays[agent_id].poll() is None:
            self._log(f"Agent {agent_id} již běží."); return
        try:
            script_path = os.path.join(os.path.dirname(__file__), "cdp_agent.py")
            if not os.path.exists(script_path):
                self._log(f"❌ Kritická chyba: Soubor 'cdp_agent.py' nenalezen!"); return
            
            self._log(f"Spouštím agenta '{agent_id}'...");
            
            # Určíme správný spouštěcí program Pythonu a příznaky pro zobrazení konzole
            python_exec = sys.executable
            console_flags = 0
            
            # Na Windows se pokusíme zajistit zobrazení konzole i v případě, že je spuštěn pythonw.exe
            if sys.platform == "win32":
                console_flags = subprocess.CREATE_NEW_CONSOLE
                if python_exec.lower().endswith("pythonw.exe"):
                    potential_python_exe = os.path.join(os.path.dirname(python_exec), "python.exe")
                    if os.path.exists(potential_python_exe):
                        python_exec = potential_python_exe
                        self._log(f"Přepnuto na '{python_exec}' pro zobrazení konzole.")
                    else:
                        self._log(f"Upozornění: '{sys.executable}' je pythonw.exe, ale 'python.exe' nenalezeno v adresáři '{os.path.dirname(sys.executable)}'. Konzole se nemusí zobrazit.")
            
            process = subprocess.Popen([python_exec, script_path, url], creationflags=console_flags)
            
            self.active_relays[agent_id] = process
            self._log(f"✅ Proces pro '{agent_id}' spuštěn. Cílová URL: {url}")
        except Exception as e:
            self._log(f"❌ Chyba spuštění procesu pro '{agent_id}': {e}")
        self.broadcast_status()

    def handle_bridge_event(self, event_type: str, data: Any):
        if event_type in ['connect', 'disconnect']:
            self._log(data); self.broadcast_status(); return
        
        if event_type == 'message':
            msg_type = data.metadata.get('type')
            if msg_type == 'system_command' and data.content == 'shutdown':
                self._log("Obdržen příkaz k vypnutí z GUI. Ukončuji vše..."); self.stop(); return
            
            if msg_type == 'launch_agent':
                content = data.content
                self._launch_agent(agent_id=content.get('agent_id'), url=content.get('url'))

    def broadcast_status(self):
        if self.bridge.connected:
            statuses = {"manager": ("Online", "green")}
            all_known_agents = set(self.active_relays.keys())
            for agent_id in all_known_agents:
                process = self.active_relays.get(agent_id)
                if process and process.poll() is None:
                    statuses[agent_id] = ("Online", "green")
            status_msg = SimpleMessage('System', statuses, 'incoming', msg_type='status_update')
            self.bridge.send_to_gui(status_msg)
        if self.root.winfo_exists(): self.root.after(5000, self.broadcast_status)

    def _log(self, message: str):
        if self.root.winfo_exists():
            self.root.after_idle(lambda: [self.log_view.insert("end", f"[{datetime.now().strftime('%H:%M:%S')}] {message}\n"), self.log_view.see("end")])
    
    def stop(self):
        self._log("Ukončuji podřízené procesy...")
        for agent_id, process in self.active_relays.items():
            if process.poll() is None:
                process.terminate()
                self._log(f"Proces pro {agent_id} byl ukončen.")
        self._log("Zastavuji bridge a ukončuji manažer."); self.bridge.stop()
        if self.root.winfo_exists(): self.root.destroy()
        sys.exit(0)

if __name__ == "__main__":
    manager = RelayManager()
    manager.start()
