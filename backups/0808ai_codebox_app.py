#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox, simpledialog
import os
import sys
import json
import subprocess
import threading
from datetime import datetime
import socket

from PIL import Image, ImageTk
from dotenv import load_dotenv
import google.generativeai as genai

load_dotenv()

# --- Globální konfigurace a styl ---
BG_COLOR = '#1e1e1e'
PANEL_BG = '#2d2d2d'
ACCENT_COLOR = '#00ffff'
FONT_FAMILY = "Consolas"

class SimpleMessage:
    def __init__(self, agent_id, content, direction, msg_type="chat", msg_id=None, metadata=None): self.agent_id, self.content, self.direction, self.timestamp, self.msg_id, self.metadata = agent_id, content, direction, datetime.now().isoformat(), msg_id, metadata or {}; self.metadata['type'] = msg_type
    def to_json(self): return json.dumps(self.__dict__, ensure_ascii=False)
    @classmethod
    def from_json(cls, json_str): data = json.loads(json_str); instance = cls(data.get('agent_id'), data.get('content'), data.get('direction')); instance.__dict__.update(data); return instance

class BridgeClient:
    def __init__(self, host='localhost', port=9999): self.host, self.port, self.socket, self.connected, self.running, self.callbacks = host, port, None, False, False, []
    def connect(self):
        if self.connected: return True
        try: self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM); self.socket.settimeout(2); self.socket.connect((self.host, self.port)); self.socket.settimeout(None); self.connected, self.running = True, True; threading.Thread(target=self._listen_for_messages, daemon=True).start(); return True
        except: return False
    def _listen_for_messages(self):
        buffer = ""
        while self.running:
            try:
                data = self.socket.recv(4096).decode('utf-8')
                if not data: break
                buffer += data
                while '\n' in buffer:
                    line, buffer = buffer.split('\n', 1)
                    if line.strip():
                        msg = SimpleMessage.from_json(line)
                        for callback in self.callbacks: root.after_idle(callback, msg)
            except: break
        self.connected = False; root.after_idle(lambda: self.callbacks[0](SimpleMessage('System', {'manager': ('Offline', 'red')}, 'incoming', msg_type='status_update')))
    def send_message(self, message: SimpleMessage):
        if not self.connected: return False
        try: self.socket.sendall((message.to_json() + '\n').encode('utf-8')); return True
        except: return False
    def add_callback(self, callback):
        if callback not in self.callbacks: self.callbacks.append(callback)
    def stop(self): self.running = False; self.socket.close() if self.socket else None

class FilesPanel:
    def __init__(self, parent, callback=None):
        self.callback, self.current_dir = callback, os.getcwd(); self.frame = ttk.Frame(parent, style='FilesPanel.TFrame'); toolbar = ttk.Frame(self.frame, style='Toolbar.TFrame'); toolbar.pack(fill="x", padx=5, pady=2); ttk.Button(toolbar, text="↑", command=self.go_up, width=3).pack(side="left"); ttk.Button(toolbar, text="🔄", command=self.refresh, width=3).pack(side="left"); ttk.Button(toolbar, text="📁", command=self.new_folder, width=3).pack(side="left"); ttk.Button(toolbar, text="📄", command=self.new_file, width=3).pack(side="left"); self.dir_label = ttk.Label(toolbar, text=self.current_dir, foreground=ACCENT_COLOR); self.dir_label.pack(side="left", padx=(10,0)); self.tree = ttk.Treeview(self.frame, height=15); self.tree.pack(fill="both", expand=True, padx=5, pady=5); sb = ttk.Scrollbar(self.frame, orient="vertical", command=self.tree.yview); self.tree.configure(yscrollcommand=sb.set); sb.pack(side="right", fill="y"); self.tree.bind("<Double-Button-1>", self.on_double_click); self.refresh()
    def refresh(self, path=None):
        target_path = path if path else self.current_dir
        if not os.path.exists(target_path) or not os.path.isdir(target_path): print(f"Error: Path does not exist: {target_path}"); return
        self.current_dir = target_path; self.tree.delete(*self.tree.get_children()); self.dir_label.config(text=self.current_dir)
        try:
            items = sorted(os.listdir(self.current_dir))
            [self.tree.insert("", "end", text=f"📁 {i}", values=(os.path.join(self.current_dir, i),"dir")) for i in items if os.path.isdir(os.path.join(self.current_dir, i))]
            [self.tree.insert("", "end", text=f"📄 {i}", values=(os.path.join(self.current_dir, i),"file",os.path.getsize(os.path.join(self.current_dir, i)))) for i in items if os.path.isfile(os.path.join(self.current_dir, i))]
        except PermissionError: self.tree.insert("", "end", text="❌ Access Denied", values=("", "error"))
    def go_up(self): parent = os.path.dirname(self.current_dir); self.refresh(parent) if parent != self.current_dir else None
    def on_double_click(self, e):
        if not (sel := self.tree.selection()): return
        item = self.tree.item(sel[0]); path, typ = item['values'][0], item['values'][1]
        self.refresh(path) if typ == 'dir' else (self.callback(path) if typ == 'file' and self.callback else None)
    def new_folder(self):
        if name := simpledialog.askstring("New Folder","Folder name:"):
            try: os.makedirs(os.path.join(self.current_dir,name), exist_ok=True); self.refresh()
            except Exception as e: messagebox.showerror("Error", f"Cannot create folder: {e}")
    def new_file(self):
        if name := simpledialog.askstring("New File","File name:"):
            try: path = os.path.join(self.current_dir,name); open(path,'w').close(); self.refresh(); self.callback(path) if self.callback else None
            except Exception as e: messagebox.showerror("Error", f"Cannot create file: {e}")

class AppAPI:
    def __init__(self, app_instance):
        self.app = app_instance
    def list_files(self, path=None):
        full_path = os.path.abspath(path if path else self.app.files_panel.current_dir)
        self.app.files_panel.refresh(full_path)
        self.app._update_status_banner(f"Zobrazen obsah: {full_path}")
    def open_file(self, path):
        self.app.open_file_in_viewer(path)
        self.app._update_status_banner(f"Otevřen soubor: {path}")
    def create_file(self, path):
        open(path, 'w').close()
        self.app.files_panel.refresh(os.path.dirname(path))
        self.app._update_status_banner(f"Vytvořen prázdný soubor: {path}")
    def save_file(self):
        self.app._save_current_file()
    def write_file(self, path, content):
        try:
            dir_name = os.path.dirname(path)
            if dir_name: os.makedirs(dir_name, exist_ok=True)
            with open(path, 'w', encoding='utf-8') as f: f.write(content)
            self.app._update_status_banner(f"✅ Soubor '{os.path.basename(path)}' byl zapsán.")
            self.app.files_panel.refresh(os.path.dirname(path))
        except Exception as e:
            self.app._update_status_banner(f"❌ Chyba při zápisu do souboru {path}: {e}")
    def execute_command(self, command_line):
        self.app._update_status_banner(f"Spouštím: {command_line}")
        try:
            process = subprocess.Popen(
                command_line, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding='utf-8', errors='replace'
            )
            def read_output():
                for line in iter(process.stdout.readline, ''):
                    self.app.root.after_idle(self.app._update_status_banner, line.strip())
                process.stdout.close()
                process.wait()
                self.app.root.after_idle(self.app._update_status_banner, f"✅ Příkaz '{command_line}' dokončen.")
            threading.Thread(target=read_output, daemon=True).start()
        except Exception as e:
            self.app._update_status_banner(f"❌ Chyba při spouštění příkazu: {e}")

class AiCodeBoxApp:
    def __init__(self, root):
        self.root = root
        self.root.title("AI Code Box")
        self.root.geometry("1600x900")

        try:
            bg_image_path = os.path.join(os.path.dirname(__file__), "background.jpg")
            bg_image = Image.open(bg_image_path)
            self.bg_photo = ImageTk.PhotoImage(bg_image)
            self.background_label = tk.Label(root, image=self.bg_photo)
            self.background_label.place(x=0, y=0, relwidth=1, relheight=1)
        except Exception as e:
            print(f"Chyba načtení pozadí: {e}")
            self.root.configure(bg=BG_COLOR)
            self.background_label = None

        self.bridge_client = BridgeClient(); self.bridge_client.add_callback(self._handle_bridge_message)
        self.agents = ["A1", "A2", "A3"]; self.recipient_vars = {agent_id: tk.BooleanVar(value=True) for agent_id in self.agents}
        self.gemini = None; self.gemini_system_prompt = ""; self.api = AppAPI(self)
        self.status_indicators = {}; self.status_banner_label = None
        self.expanded_section = 'team_comm_frame'
        self.has_new_content = {
            'team_comm_frame': False,
            'file_viewer_frame': False,
            'api_chat_frame': False
        }
        self._setup_gui()
        self._setup_gemini()
        self.root.after(1000, self.connect_or_launch_manager)
        self.root.after(2000, self.load_manifest_and_init_gemini)
        self.root.protocol("WM_DELETE_WINDOW", self.shutdown_full_system)

    def _toggle_section(self, section_name):
        frames = {
            'team_comm_frame': self.team_comm_frame,
            'file_viewer_frame': self.file_viewer_frame,
            'api_chat_frame': self.api_chat_frame
        }
        
        if self.expanded_section == section_name:
            self.expanded_section = None
            for name, frame in frames.items():
                self._update_title_color(frame, name)
                frame.pack(fill='both', expand=True, pady=5, padx=5)
        else:
            self.expanded_section = section_name
            for name, frame in frames.items():
                if name == section_name:
                    frame.pack(fill='both', expand=True, pady=5, padx=5)
                    self.has_new_content[name] = False
                    self._update_title_color(frame, name)
                else:
                    self._update_title_color(frame, name)
                    frame.pack(fill='x', expand=False, pady=5, padx=5)

    def _update_title_color(self, frame, section_name):
        title_label = frame.winfo_children()[0].winfo_children()[0]
        if self.has_new_content[section_name]:
            title_label.config(foreground='orange')
        else:
            title_label.config(foreground=ACCENT_COLOR)

    def _setup_gui(self):
        style = ttk.Style()
        style.theme_use('clam')
        style.configure('TFrame', background=BG_COLOR, borderwidth=1, relief="solid", bordercolor=ACCENT_COLOR)
        style.configure('TLabel', background=BG_COLOR, foreground=ACCENT_COLOR, font=(FONT_FAMILY, 10))
        style.configure('TButton', background=PANEL_BG, foreground=ACCENT_COLOR, font=(FONT_FAMILY, 10))
        style.configure('TCheckbutton', background=BG_COLOR, foreground=ACCENT_COLOR, font=(FONT_FAMILY, 10))
        style.map('TButton',
                  background=[('active', ACCENT_COLOR), ('!disabled', PANEL_BG)],
                  foreground=[('active', 'black'), ('!disabled', ACCENT_COLOR)])
        style.configure('Treeview', background=PANEL_BG, foreground=ACCENT_COLOR, fieldbackground=PANEL_BG)
        style.configure('Treeview.Heading', font=(FONT_FAMILY, 10, 'bold'))
        
        main = ttk.Frame(self.root, style='Transparent.TFrame')
        main.pack(fill="both", expand=True, padx=10, pady=(150, 10))
        
        main_paned_window = ttk.PanedWindow(main, orient='horizontal')
        main_paned_window.pack(fill='both', expand=True)

        left_side_panel = ttk.Frame(main_paned_window, width=250, style='Transparent.TFrame')
        main_paned_window.add(left_side_panel, weight=10)
        ttk.Label(left_side_panel, text="📁 File Manager", font=(FONT_FAMILY, 12, 'bold')).pack(pady=(0,5), padx=5, anchor='w')
        fp_frame = ttk.Frame(left_side_panel); fp_frame.pack(fill="both", expand=True, padx=5, pady=5)
        self.files_panel = FilesPanel(fp_frame, callback=self.open_file_in_viewer)
        self.files_panel.frame.pack(fill="both", expand=True)
        
        center_frame = ttk.Frame(main_paned_window, style='Transparent.TFrame')
        main_paned_window.add(center_frame, weight=80)
        
        self.team_comm_frame = ttk.Frame(center_frame, name='team_comm_frame')
        self.file_viewer_frame = ttk.Frame(center_frame, name='file_viewer_frame')
        self.api_chat_frame = ttk.Frame(center_frame, name='api_chat_frame')

        for frame, title, name in zip([self.team_comm_frame, self.file_viewer_frame, self.api_chat_frame], ["Team Communication", "File Viewer", "API Chat"], ['team_comm_frame', 'file_viewer_frame', 'api_chat_frame']):
            title_frame = ttk.Frame(frame, style='CollapsedTitle.TFrame')
            title_frame.pack(fill='x', expand=False)
            label = ttk.Label(title_frame, text=f"🤖 {title}", font=(FONT_FAMILY, 12, 'bold'), foreground=ACCENT_COLOR)
            label.pack(side='left', padx=5, pady=2)
            label.bind("<Button-1>", lambda event, n=name: self._toggle_section(n))
        
        status_fr = ttk.Frame(self.team_comm_frame); status_fr.pack(fill="x", pady=5, padx=5)
        for agent_id in self.agents:
            fr = ttk.Frame(status_fr); fr.pack(side='left', padx=5)
            btn = ttk.Button(fr, text=agent_id, width=4, command=lambda a=agent_id: self.activate_agent_view(a)); btn.pack(side="left")
            ttk.Checkbutton(fr, text="Send", variable=self.recipient_vars[agent_id]).pack(side="right")
        self.team_view = scrolledtext.ScrolledText(self.team_comm_frame, height=10, bg=PANEL_BG, fg=ACCENT_COLOR, wrap="word", font=(FONT_FAMILY, 10)); self.team_view.pack(fill="both", expand=True, pady=(0,5), padx=5)
        self.team_input = tk.Text(self.team_comm_frame, height=3, bg=PANEL_BG, fg=ACCENT_COLOR, wrap="word", font=(FONT_FAMILY, 10)); self.team_input.pack(fill="x", pady=5, padx=5)
        self.team_view.tag_configure("user_message", justify="right", background="#004d40", foreground="white", rmargin=10)
        self.team_view.tag_configure("agent_message", justify="left", rmargin=10)
        self.team_input.bind("<Return>", lambda event: self.handle_send_keypress(event, self.send_to_team_from_input)); self.team_input.bind("<Shift-Return>", self.handle_newline_keypress)
        ttk.Button(self.team_comm_frame, text="Send to Team", command=self.send_to_team_from_input).pack(fill="x", pady=(0, 5), padx=5)

        file_header = ttk.Frame(self.file_viewer_frame); file_header.pack(fill="x", padx=5, pady=5)
        self.current_file_label = ttk.Label(file_header, text="No file selected", foreground=ACCENT_COLOR, font=(FONT_FAMILY, 10, 'italic'))
        self.current_file_label.pack(side="left")
        ttk.Button(file_header, text="💾 Save", command=self.api.save_file).pack(side="right")
        self.file_text = scrolledtext.ScrolledText(self.file_viewer_frame, height=10, bg=PANEL_BG, fg=ACCENT_COLOR, wrap="none", font=(FONT_FAMILY, 10)); self.file_text.pack(fill="both",expand=True,pady=5, padx=5)
        
        self.api_view = scrolledtext.ScrolledText(self.api_chat_frame, height=10, bg=PANEL_BG, fg=ACCENT_COLOR, wrap="word", font=(FONT_FAMILY, 10)); self.api_view.pack(fill="both", expand=True, pady=(0,5), padx=5)
        
        api_input_frame = ttk.Frame(self.api_chat_frame)
        api_input_frame.pack(fill="x", padx=5, pady=5)
        self.api_input = tk.Text(api_input_frame, height=3, bg=PANEL_BG, fg=ACCENT_COLOR, wrap="word", font=(FONT_FAMILY, 10))
        self.api_input.pack(fill="both", expand=True, side="left", padx=(0, 5))
        ttk.Button(api_input_frame, text="Send to Gemini", command=self.send_to_api).pack(side="right")
        
        self.api_view.tag_configure("user_message", justify="right", background="#004d40", foreground="white", rmargin=10)
        self.api_view.tag_configure("agent_message", justify="left", foreground=ACCENT_COLOR, rmargin=10)
        self.api_view.tag_configure("system_message", justify="left", foreground="orange", rmargin=10)
        self.api_input.bind("<Return>", lambda event: self.handle_send_keypress(event, self.send_to_api))
        self.api_input.bind("<Shift-Return>", self.handle_newline_keypress)

        self._toggle_section(self.expanded_section)

        right_side_panel = ttk.Frame(main_paned_window, width=250, style='Transparent.TFrame')
        main_paned_window.add(right_side_panel, weight=10)
        ttk.Label(right_side_panel, text="📊 Stav Systému", font=(FONT_FAMILY, 12, 'bold')).pack(pady=(0,10), padx=5, anchor='w')
        components = {"manager": "Relay Manager", "gemini": "Gemini API", "A1": "Agent A1", "A2": "Agent A2", "A3": "Agent A3"}
        for key, text in components.items():
            frame = ttk.Frame(right_side_panel); frame.pack(fill='x', padx=5, pady=2)
            ttk.Label(frame, text=f"{text}:").pack(side='left', padx=5)
            label = ttk.Label(frame, text="Unknown", foreground="grey", anchor='e')
            label.pack(side='right', padx=5)
            self.status_indicators[key] = label
        ttk.Separator(right_side_panel, orient='horizontal').pack(fill='x', pady=10, padx=5)
        ttk.Label(right_side_panel, text="📋 Poslední zpráva", font=(FONT_FAMILY, 10, 'bold')).pack(anchor='w', padx=5)
        self.status_banner_label = ttk.Label(right_side_panel, text="Systém se spouští...", foreground="orange", wraplength=200, anchor='nw', justify='left'); self.status_banner_label.pack(fill='x', pady=5, padx=5)
        ttk.Button(right_side_panel, text="🔴 Ukončit Vše", command=self.shutdown_full_system).pack(side='bottom', fill="x", pady=5, padx=5)

    def handle_send_keypress(self, event, send_function): send_function(); return "break"
    def handle_newline_keypress(self, event): pass

    def _setup_gemini(self):
        try:
            api_key = os.getenv('GEMINI_API_KEY')
            if api_key:
                genai.configure(api_key=api_key)
                self.gemini = genai.GenerativeModel('gemini-2.5-flash')
                self._update_status_panel({'gemini': ('Online', 'green')})
                self._update_status_banner("Gemini API (2.5 Flash) je online.")
            else:
                self.gemini = None; self._update_status_panel({'gemini': ('Klíč chybí', 'red')})
        except Exception as e:
            self.gemini = None; self._update_status_panel({'gemini': ('Chyba', 'red')}); self._update_status_banner(f"Chyba Gemini API: {e}")

    def load_manifest_and_init_gemini(self):
        manifest_path = os.path.join(os.path.dirname(__file__), "welcome", "nova_codebox_manifest.json")
        try:
            with open(manifest_path, 'r', encoding='utf-8') as f: manifest_data = json.load(f)
            prompt_lines = manifest_data.get("geminiSystemPrompt", [])
            self.gemini_system_prompt = "\n".join(prompt_lines)
            if not self.gemini_system_prompt: self._update_status_banner("V manifestu chybí 'geminiSystemPrompt'."); return
            if not self.gemini: return
            welcome_prompt = "Jsem AI Code Box, připraven k příjmu instrukcí. Potvrď příjem."
            threading.Thread(target=self._generate_gemini_response, args=(welcome_prompt, False)).start()
        except Exception as e: self._update_status_banner(f"Chyba při načítání manifestu: {e}")

    def _generate_gemini_response(self, prompt, is_user_request=False):
        try:
            full_prompt = f"{self.gemini_system_prompt}\n\nUživatel: {prompt}" if is_user_request else prompt
            response = self.gemini.generate_content(full_prompt)
            if is_user_request: self.root.after_idle(lambda: self._process_gemini_command(response.text))
            else: self.root.after_idle(lambda: self._display("Gemini-API", response.text, self.api_view, tag="agent_message"))
        except Exception as e: self.root.after_idle(lambda: self._update_status_banner(f"Chyba komunikace s Gemini: {e}"))

    def _process_gemini_command(self, response_text: str):
        self._display("Gemini-API", response_text, self.api_view, tag="agent_message")
        try:
            start_index = response_text.find('{'); end_index = response_text.rfind('}')
            if start_index != -1 and end_index != -1 and end_index > start_index:
                json_text = response_text[start_index : end_index + 1]
                data = json.loads(json_text)
                command_name = data.get("command")
                command_method = getattr(self.api, command_name, None)
                if command_method:
                    self._update_status_banner(f"Provádím příkaz: {command_name}...")
                    args = data.copy(); del args['command']
                    command_method(**args)
                else: self._update_status_banner(f"Neznámý příkaz od Gemini: {command_name}")
        except json.JSONDecodeError: self._update_status_banner("V odpovědi byl nalezen JSON, ale je neplatný.")
        except Exception as e: self._update_status_banner(f"Chyba při vykonávání příkazu: {e}")
        
    def send_to_api(self):
        txt = self.api_input.get("1.0","end-1c").strip()
        if not txt: return
        self.api_input.delete("1.0","end"); self._display("You", txt, self.api_view, tag="user_message")
        if not self.gemini: self._update_status_banner("Gemini není nakonfigurováno."); return
        threading.Thread(target=self._generate_gemini_response, args=(txt, True)).start()

    def _handle_bridge_message(self, msg: SimpleMessage):
        if msg.metadata.get('type') == 'status_update': self._update_status_panel(msg.content); return
        if msg.direction == "incoming":
            self.has_new_content['team_comm_frame'] = True
            self._display(msg.agent_id, msg.content, self.team_view, tag="agent_message")

    def _update_status_panel(self, statuses):
        for key, value in statuses.items():
            if key in self.status_indicators:
                status_text, status_color = value
                self.status_indicators[key].config(text=status_text, foreground=status_color)
                self.root.update_idletasks()
    
    def _update_status_banner(self, text: str):
        if self.status_banner_label: self.status_banner_label.config(text=text)

    def shutdown_full_system(self):
        self._update_status_banner("Zahajuji kompletní vypnutí systému...")
        shutdown_msg = SimpleMessage('System', 'shutdown', 'outgoing', msg_type='system_command')
        self.bridge_client.send_message(shutdown_msg)
        self.root.after(500, self.on_closing)

    def on_closing(self): self.bridge_client.stop(); self.root.destroy()
    def send_to_team_from_input(self):
        content = self.team_input.get("1.0", "end-1c").strip()
        if not content: return
        self.team_input.delete("1.0", "end"); self._display("You", content, self.team_view, tag="user_message")
        selected_agents = [agent for agent, var in self.recipient_vars.items() if var.get()]
        if not selected_agents: self._update_status_banner("Nevybrán žádný příjemce pro týmovou zprávu."); return
        for agent_id in selected_agents: msg = SimpleMessage(agent_id=agent_id, content=content, direction="outgoing", msg_type="chat"); self.bridge_client.send_message(msg)
    
    def _display(self, author: str, msg: str, widget, tag=None):
        if tag is None: tag = "user_message" if author == "You" else "agent_message"
        final_msg = f"[{datetime.now().strftime('%H:%M:%S')}] {author}:\n{msg}\n\n"; widget.insert("end", final_msg, tag); widget.see("end")

    def _save_current_file(self):
        filename = self.current_file_label.cget("text").replace("📄 ","")
        if filename == "No file selected": self._update_status_banner("Není vybrán soubor k uložení."); return
        try:
            path = os.path.join(self.files_panel.current_dir, filename)
            with open(path, 'w', encoding='utf-8') as f: f.write(self.file_text.get("1.0", "end-1c"))
            self._update_status_banner(f"Soubor {filename} úspěšně uložen.")
        except Exception as e: self._update_status_banner(f"Chyba při uložení souboru: {e}")

    def open_file_in_viewer(self, path):
        self.has_new_content['file_viewer_frame'] = True
        try:
            with open(path, 'r', encoding='utf-8') as f: content = f.read()
            self.file_text.delete("1.0", "end"); self.file_text.insert("1.0", content); self.current_file_label.config(text=f"📄 {os.path.basename(path)}")
        except Exception as e: self._update_status_banner(f"Chyba při otevření souboru: {e}")
    
    def activate_agent_view(self, agent_id: str): self._update_status_banner(f"Posílám požadavek na aktivaci pro {agent_id}..."); msg = SimpleMessage(agent_id=agent_id, content=f"Activate view", direction="outgoing", msg_type="activate_relay"); self.bridge_client.send_message(msg)
    
    def connect_or_launch_manager(self):
        self._update_status_banner("Hledám Relay Server...")
        if self.bridge_client.connect(): self._update_status_banner("Připojeno k Relay Serveru.")
        else:
            self._update_status_banner("Relay Server neběží, spouštím..."); script_dir = os.path.dirname(os.path.abspath(__file__)); server_script = os.path.join(script_dir, "relay_server.py")
            if not os.path.exists(server_script): msg = f"Soubor '{server_script}' nenalezen!"; self._update_status_banner(msg); return
            try: subprocess.Popen([sys.executable, server_script], cwd=script_dir); self.root.after(3000, self.retry_connection)
            except Exception as e: self._update_status_banner(f"Chyba spuštění Relay Serveru: {e}")
    
    def retry_connection(self): self._update_status_banner("Zkouším se znovu připojit..."); self._update_status_banner("Úspěšně připojeno.") if self.bridge_client.connect() else self._update_status_banner("Připojení selhalo.")

if __name__ == "__main__":
    root = tk.Tk()
    app = AiCodeBoxApp(root)
    root.mainloop()