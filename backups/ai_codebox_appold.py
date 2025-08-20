#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
import os
import sys
import json
import subprocess
import threading
import time
import google.generativeai as genai
from datetime import datetime
from queue import Queue, Empty
from typing import Dict, Optional, Callable, Any

# =============================================================================
# SIMPLE RELAY CLASSES
# =============================================================================

class SimpleMessage:
    """Jednoduchá zpráva s ID a základními údaji"""
    def __init__(self, agent_id: str, content: str, direction: str, msg_id: Optional[int] = None):
        self.id = msg_id
        self.agent_id = agent_id
        self.content = content
        self.direction = direction  # 'incoming' nebo 'outgoing'
        self.timestamp = datetime.now().isoformat()

    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'agent_id': self.agent_id,
            'content': self.content,
            'direction': self.direction,
            'timestamp': self.timestamp
        }

class SimpleRelay:
    """Jednoduchý relay pro jednoho agenta"""
    def __init__(self, agent_id: str):
        self.agent_id = agent_id
        self.inbox = Queue()   # Zprávy z webu -> chatbox
        self.outbox = Queue()  # Zprávy chatbox -> web
        self.message_counter = 0
        self.is_active = True

    def receive_from_web(self, content: str) -> int:
        """Přijme zprávu z webu, vrátí ID"""
        msg = SimpleMessage(self.agent_id, content, 'incoming', self.message_counter)
        self.inbox.put(msg)
        self.message_counter += 1
        return msg.id

    def send_to_web(self, content: str) -> None:
        """Pošle zprávu na web (bez ID)"""
        msg = SimpleMessage(self.agent_id, content, 'outgoing')
        self.outbox.put(msg)

    def get_next_to_chatbox(self) -> Optional[SimpleMessage]:
        try:
            return self.inbox.get_nowait()
        except Empty:
            return None

    def get_next_from_chatbox(self) -> Optional[SimpleMessage]:
        try:
            return self.outbox.get_nowait()
        except Empty:
            return None

class RelayManager:
    """Správce všech relay"""
    def __init__(self):
        self.relays: Dict[str, SimpleRelay] = {}
        self.message_handlers: list[Callable] = []
        self.monitoring_thread = None
        self.is_monitoring = False

    def create_relay(self, agent_id: str) -> SimpleRelay:
        relay = SimpleRelay(agent_id)
        self.relays[agent_id] = relay
        return relay

    def get_relay(self, agent_id: str) -> Optional[SimpleRelay]:
        return self.relays.get(agent_id)

    def has_relay(self, agent_id: str) -> bool:
        return agent_id in self.relays

    def remove_relay(self, agent_id: str) -> bool:
        if agent_id in self.relays:
            self.relays[agent_id].is_active = False
            del self.relays[agent_id]
            return True
        return False

    def send_to_agent(self, agent_id: str, content: str) -> bool:
        relay = self.get_relay(agent_id)
        if relay:
            relay.send_to_web(content)
            return True
        return False

    def add_message_handler(self, handler: Callable):
        self.message_handlers.append(handler)

    def start_monitoring(self):
        if not self.is_monitoring:
            self.is_monitoring = True
            self.monitoring_thread = threading.Thread(
                target=self._monitor_messages, daemon=True
            )
            self.monitoring_thread.start()

    def stop_monitoring(self):
        self.is_monitoring = False
        if self.monitoring_thread:
            self.monitoring_thread.join(timeout=1)

    def _monitor_messages(self):
        while self.is_monitoring:
            try:
                for agent_id, relay in list(self.relays.items()):
                    if not relay.is_active:
                        continue

                    # incoming
                    while True:
                        msg = relay.get_next_to_chatbox()
                        if not msg:
                            break
                        for h in self.message_handlers:
                            try:
                                h('incoming', msg)
                            except Exception as e:
                                print(f"Handler incoming error: {e}")

                    # outgoing
                    while True:
                        msg = relay.get_next_from_chatbox()
                        if not msg:
                            break
                        for h in self.message_handlers:
                            try:
                                h('outgoing', msg)
                            except Exception as e:
                                print(f"Handler outgoing error: {e}")

                time.sleep(0.1)
            except Exception as e:
                print(f"Monitoring error: {e}")
                time.sleep(1)

# =============================================================================
# FILES PANEL
# =============================================================================

class FilesPanel:
    def __init__(self, parent, callback=None):
        self.callback = callback
        self.current_dir = os.getcwd()

        self.frame = ttk.Frame(parent)
        toolbar = ttk.Frame(self.frame)
        toolbar.pack(fill="x", padx=5, pady=2)

        ttk.Button(toolbar, text="↑", command=self.go_up, width=3).pack(side="left")
        ttk.Button(toolbar, text="🔄", command=self.refresh, width=3).pack(side="left")
        ttk.Button(toolbar, text="📁", command=self.new_folder, width=3).pack(side="left")
        ttk.Button(toolbar, text="📄", command=self.new_file, width=3).pack(side="left")

        self.dir_label = ttk.Label(toolbar, text=self.current_dir, foreground="#00ff99")
        self.dir_label.pack(side="left", padx=(10,0))

        self.tree = ttk.Treeview(self.frame, height=15)
        self.tree.pack(fill="both", expand=True, padx=5, pady=5)
        sb = ttk.Scrollbar(self.frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")

        self.tree.bind("<Double-Button-1>", self.on_double_click)
        self.refresh()

    def refresh(self):
        self.tree.delete(*self.tree.get_children())
        self.dir_label.config(text=self.current_dir)
        try:
            items = sorted(os.listdir(self.current_dir))
            for i in items:
                full = os.path.join(self.current_dir, i)
                if os.path.isdir(full):
                    self.tree.insert("", "end", text=f"📁 {i}", values=(full,"dir"))
            for i in items:
                full = os.path.join(self.current_dir, i)
                if os.path.isfile(full):
                    size = os.path.getsize(full)
                    self.tree.insert("", "end", text=f"📄 {i}", values=(full,"file",size))
        except PermissionError:
            self.tree.insert("", "end", text="❌ Access Denied", values=("", "error"))

    def refresh_tree(self, path: str):
        if os.path.dirname(path) == self.current_dir:
            self.refresh()

    def go_up(self):
        parent = os.path.dirname(self.current_dir)
        if parent != self.current_dir:
            self.current_dir = parent
            self.refresh()

    def on_double_click(self, e):
        sel = self.tree.selection()
        if not sel:
            return
        item = self.tree.item(sel[0])
        path, typ = item['values'][0], item['values'][1]
        if typ == 'dir':
            self.current_dir = path
            self.refresh()
        elif typ == 'file' and self.callback:
            self.callback(path)

    def new_folder(self):
        name = tk.simpledialog.askstring("New Folder","Folder name:")
        if not name: return
        try:
            os.makedirs(os.path.join(self.current_dir,name), exist_ok=True)
            self.refresh()
        except Exception as e:
            messagebox.showerror("Error", f"Cannot create folder: {e}")

    def new_file(self):
        name = tk.simpledialog.askstring("New File","File name:")
        if not name: return
        try:
            path = os.path.join(self.current_dir,name)
            open(path,'w').close()
            self.refresh()
            if self.callback:
                self.callback(path)
        except Exception as e:
            messagebox.showerror("Error", f"Cannot create file: {e}")

# =============================================================================
# MAIN APPLICATION
# =============================================================================

class AiCodeBoxApp:
    def __init__(self, root):
        self.root = root
        self.root.title("AI Code Box - Nova v4.0")
        self.root.geometry("1400x900")
        self.root.configure(bg="#1e1e1e")

        # directories
        self.memory_dir = "memory"
        self.welcome_dir = "welcome"
        self.images_dir = "images"
        for d in (self.memory_dir, self.welcome_dir, self.images_dir):
            os.makedirs(d, exist_ok=True)

        self.chat_memory_path = os.path.join(self.memory_dir, "code_box_chatbox.json")
        self.wip_path         = os.path.join(self.memory_dir, "nova_codebox_history.json")

        # relay manager
        self.relay_manager = RelayManager()
        self.relay_manager.add_message_handler(self._handle_relay_message)
        self.relay_manager.start_monitoring()

        # agents
        self.agents = ["A1","A2","A3"]
        self.agents_map = {
            "A1": {"name":"Copilot", "url":"https://copilot.microsoft.com"},
            "A2": {"name":"Gemini",  "url":"https://gemini.google.com"},
            "A3": {"name":"Claude",  "url":"https://claude.ai"}
        }

        # data
        self.chat_memory = self._load_json(self.chat_memory_path, default=[])
        self.wip_chats   = self._load_json(self.wip_path, default={})

        # GUI vars
        self.active_chat_id = tk.StringVar()
        self.recipient_vars = [tk.BooleanVar() for _ in self.agents]

        # setup
        self._setup_gui()
        self._setup_gemini()

        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

    def _load_json(self, path, default):
        try:
            if os.path.exists(path):
                with open(path, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except:
            pass
        return default

    def _setup_gui(self):
        main = ttk.Frame(self.root); main.pack(fill="both",expand=True, padx=10,pady=10)

        # left
        left = ttk.Frame(main, width=350); left.pack(side="left",fill="y",padx=(0,10))
        left.pack_propagate(False)

        ttk.Label(left, text="📁 File Manager", font=("Arial",12,"bold")).pack(pady=(0,5))
        fp_frame = ttk.Frame(left,height=300); fp_frame.pack(fill="x",pady=(0,10)); fp_frame.pack_propagate(False)
        self.files_panel = FilesPanel(fp_frame, callback=self.open_file_in_viewer)
        self.files_panel.frame.pack(fill="both",expand=True)

        ttk.Label(left, text="👥 Team Communication", font=("Arial",12,"bold")).pack(pady=(10,5))
        status = ttk.Frame(left); status.pack(fill="x",pady=(0,5))
        self.status_labels = []
        for i,a in enumerate(self.agents):
            fr = ttk.Frame(status); fr.pack(fill="x", pady=1)
            btn = ttk.Button(fr, text=a, width=4, command=lambda a=a: self.open_web_relay(a))
            btn.pack(side="left")
            lbl = ttk.Label(fr, text=f"{a}: Offline", foreground="gray"); lbl.pack(side="left",padx=(5,0))
            self.status_labels.append(lbl)
            ttk.Checkbutton(fr, variable=self.recipient_vars[i]).pack(side="right")

        self.team_view = scrolledtext.ScrolledText(
            left, height=15, bg="#2d2d2d", fg="#fff", insertbackground="#fff", wrap="word"
        ); self.team_view.pack(fill="both",expand=True,pady=(0,10))

        self.team_input = tk.Text(left,height=3,bg="#2d2d2d",fg="#fff",insertbackground="#fff",wrap="word")
        self.team_input.pack(fill="x",pady=(0,5))
        self.team_input.bind("<Control-Return>", lambda e: self.send_to_team_from_input())
        ttk.Button(left, text="Send to Team", command=self.send_to_team_from_input).pack(fill="x")

        # right
        right = ttk.Frame(main); right.pack(side="right",fill="both",expand=True)
        ttk.Label(right, text="📄 File Viewer", font=("Arial",12,"bold")).pack(pady=(0,5))
        self.current_file_label = ttk.Label(right, text="No file selected", foreground="#888")
        self.current_file_label.pack(pady=(0,5))
        self.file_text = scrolledtext.ScrolledText(
            right, height=20, bg="#2d2d2d", fg="#fff", insertbackground="#fff", wrap="none"
        ); self.file_text.pack(fill="both",expand=True,pady=(0,10))

        ttk.Label(right, text="🤖 API Chat & Relay Log", font=("Arial",12,"bold")).pack(pady=(10,5))
        self.api_view = scrolledtext.ScrolledText(
            right, height=10, bg="#2d2d2d", fg="#0f0", insertbackground="#fff", wrap="word"
        ); self.api_view.pack(fill="both",expand=True,pady=(0,10))

        api_frame = ttk.Frame(right); api_frame.pack(fill="x")
        self.api_input = tk.Text(api_frame,height=3,bg="#2d2d2d",fg="#fff",insertbackground="#fff",wrap="word")
        self.api_input.pack(fill="both",expand=True,side="left",padx=(0,5))
        self.api_input.bind("<Control-Return>", lambda e: self.send_to_api())
        ttk.Button(api_frame, text="Send", command=self.send_to_api).pack(side="right")

    def _setup_gemini(self):
        try:
            key = os.getenv('GEMINI_API_KEY')
            if not key and os.path.exists('.env'):
                with open('.env','r') as f:
                    for l in f:
                        if l.startswith('GEMINI_API_KEY='):
                            key = l.split('=',1)[1].strip()
                            break
            if key:
                genai.configure(api_key=key)
                self.gemini = genai.GenerativeModel('gemini-pro')
                self._display("System","✅ Gemini API configured",self.api_view)
            else:
                self.gemini = None
                self._display("System","⚠️ Gemini API key not found",self.api_view)
        except Exception as e:
            self.gemini = None
            self._display("System",f"❌ Gemini API error: {e}",self.api_view)

    # -------------------------------------------------------------------------
    # RELAY MESSAGE HANDLER
    # -------------------------------------------------------------------------
    def _handle_relay_message(self, direction: str, msg: SimpleMessage):
        if direction == 'incoming':
            c = msg.content.strip()
            if c.startswith('/fm_'):
                self._handle_file_manager_command(msg)
                return
            if c.startswith('/view_'):
                self._handle_viewer_command(msg)
                return
            self._chat_receive(msg)
        else:
            self._chat_send(msg)

    def _chat_receive(self, msg: SimpleMessage):
        try:
            self._display(msg.agent_id, f"[ID:{msg.id}] {msg.content}", self.team_view)
            self._add_to_team(msg, via=msg.agent_id, relay_id=msg.id, direction=msg.direction)
            self._display("Relay", f"📥 from {msg.agent_id}: {msg.content[:50]}", self.api_view)
        except Exception as e:
            self._display("System", f"❌ receive error: {e}", self.api_view)

    def _chat_send(self, msg: SimpleMessage):
        try:
            self._display("Relay", f"📤 to {msg.agent_id}: {msg.content[:50]}", self.api_view)
            self._log_outgoing(msg)
        except Exception as e:
            self._display("System", f"❌ send error: {e}", self.api_view)

    def _add_to_team(self, msg, via, relay_id=None, direction=None):
        base = self.active_chat_id.get()
        if not base:
            now = datetime.now()
            base = f"{via}-{now:%d%m}-{now:%H%M}"
            self.active_chat_id.set(base)
        entry = {
            "id": f"{base}-{len(self.wip_chats.get(base,[]))+1}",
            "time": msg.timestamp,
            "author": msg.agent_id,
            "text": msg.content,
            "relay_id": relay_id,
            "relay_direction": direction,
            "via_relay": via
        }
        self.wip_chats.setdefault(base, []).append(entry)
        with open(self.wip_path, 'w', encoding='utf-8') as f:
            json.dump(self.wip_chats, f, indent=2, ensure_ascii=False)

    def _log_outgoing(self, msg: SimpleMessage):
        log = {
            "timestamp": msg.timestamp,
            "agent_id": msg.agent_id,
            "content": msg.content,
            "direction": "outgoing",
            "via_relay": msg.agent_id
        }
        with open(os.path.join(self.memory_dir, f"{msg.agent_id.lower()}_relay_outgoing.log"),
                  'a', encoding='utf-8') as f:
            f.write(json.dumps(log, ensure_ascii=False) + '\n')

    # -------------------------------------------------------------------------
    # FILE MANAGER COMMANDS
    # -------------------------------------------------------------------------
    def _handle_file_manager_command(self, msg: SimpleMessage):
        try:
            parts = msg.content.strip().split(' ',2)
            cmd = parts[0][4:]
            if cmd == 'list':
                res = self._fm_list(parts[1] if len(parts)>1 else '.')
            elif cmd == 'read':
                res = self._fm_read(parts[1] if len(parts)>1 else None)
            elif cmd == 'write':
                res = self._fm_write(parts[1], parts[2] if len(parts)>2 else "")
            elif cmd == 'create':
                res = self._fm_create(parts[1] if len(parts)>1 else None)
            elif cmd == 'delete':
                res = self._fm_delete(parts[1] if len(parts)>1 else None)
            elif cmd == 'mkdir':
                res = self._fm_mkdir(parts[1] if len(parts)>1 else None)
            else:
                res = f"❌ Unknown FM cmd: {cmd}"
        except Exception as e:
            res = f"❌ FM error: {e}"
        self.send_via_relay(msg.agent_id, res)

    def _fm_list(self, path: str) -> str:
        if not path: return "❌ Missing path"
        p = os.path.abspath(path)
        if not os.path.exists(p): return f"❌ Not exists: {path}"
        if not os.path.isdir(p): return f"❌ Not a dir: {path}"
        items=[]
        for i in sorted(os.listdir(p)):
            fp=os.path.join(p,i)
            if os.path.isdir(fp): items.append(f"📁 {i}/")
            else: items.append(f"📄 {i} ({os.path.getsize(fp)} b)")
        self.files_panel.refresh_tree(p)
        return "📂 "+p+"\n"+"\n".join(items)

    def _fm_read(self, fp: Optional[str]) -> str:
        if not fp: return "❌ Missing file"
        p = os.path.abspath(fp)
        if not os.path.exists(p): return f"❌ Not exists: {fp}"
        if not os.path.isfile(p): return f"❌ Not file: {fp}"
        size=os.path.getsize(p)
        if size>1024*1024: return f"❌ Too large ({size} b)"
        try:
            with open(p,'r',encoding='utf-8') as f: cnt=f.read()
        except UnicodeDecodeError:
            return f"📄 {fp} binary ({size} b)"
        self._update_viewer(p,cnt)
        if len(cnt)>2000:
            cnt=cnt[:2000]+"\n... (truncated)"
        return f"📄 {fp}\n{cnt}"

    def _fm_write(self, fp: Optional[str], cnt: str) -> str:
        if not fp: return "❌ Missing file"
        p=os.path.abspath(fp)
        os.makedirs(os.path.dirname(p),exist_ok=True)
        with open(p,'w',encoding='utf-8') as f: f.write(cnt)
        self.files_panel.refresh_tree(os.path.dirname(p))
        self._update_viewer(p,cnt)
        return f"✅ Wrote {len(cnt)} chars to {fp}"

    def _fm_create(self, fp: Optional[str]) -> str:
        if not fp: return "❌ Missing file"
        p=os.path.abspath(fp)
        if os.path.exists(p): return f"❌ Already exists: {fp}"
        os.makedirs(os.path.dirname(p),exist_ok=True)
        open(p,'w').close()
        self.files_panel.refresh_tree(os.path.dirname(p))
        return f"✅ Created empty file {fp}"

    def _fm_delete(self, fp: Optional[str]) -> str:
        if not fp: return "❌ Missing path"
        p=os.path.abspath(fp)
        if not os.path.exists(p): return f"❌ Not exists: {fp}"
        if os.path.isfile(p): os.remove(p); res=f"✅ Deleted file {fp}"
        elif os.path.isdir(p): os.rmdir(p); res=f"✅ Deleted dir {fp}"
        else: return f"❌ Unknown type: {fp}"
        self.files_panel.refresh_tree(os.path.dirname(p))
        return res

    def _fm_mkdir(self, dp: Optional[str]) -> str:
        if not dp: return "❌ Missing dir"
        p=os.path.abspath(dp)
        if os.path.exists(p): return f"❌ Already exists: {dp}"
        os.makedirs(p,exist_ok=True)
        self.files_panel.refresh_tree(p)
        return f"✅ Created dir {dp}"

    # -------------------------------------------------------------------------
    # VIEWER COMMANDS
    # -------------------------------------------------------------------------
    def _handle_viewer_command(self, msg: SimpleMessage):
        try:
            parts = msg.content.strip().split(' ',2)
            cmd = parts[0][6:]
            if cmd == 'open':
                res = self._vw_open(parts[1] if len(parts)>1 else None)
            elif cmd == 'search':
                res = self._vw_search(parts[1] if len(parts)>1 else None)
            elif cmd == 'goto':
                res = self._vw_goto(parts[1] if len(parts)>1 else None)
            elif cmd == 'info':
                res = self._vw_info()
            else:
                res = f"❌ Unknown VW cmd: {cmd}"
        except Exception as e:
            res = f"❌ VW error: {e}"
        self.send_via_relay(msg.agent_id, res)

    def _vw_open(self, fp: Optional[str]) -> str:
        if not fp: return "❌ Missing file"
        p=os.path.abspath(fp)
        if not os.path.exists(p): return f"❌ Not exists: {fp}"
        if not os.path.isfile(p): return f"❌ Not file: {fp}"
        try:
            with open(p,'r',encoding='utf-8') as f: cnt=f.read()
        except UnicodeDecodeError:
            return f"❌ Not text: {fp}"
        self._update_viewer(p,cnt)
        return f"✅ Opened {fp}: {len(cnt.splitlines())} lines, {len(cnt)} chars"

    def _vw_search(self, term: Optional[str]) -> str:
        if not term: return "❌ Missing term"
        content = self.file_text.get("1.0","end-1c")
        if not content: return "❌ Viewer empty"
        lines = content.splitlines()
        found=[]
        for i,l in enumerate(lines,1):
            if term.lower() in l.lower():
                found.append(f"Line {i}: {l.strip()}")
        if not found:
            return f"❌ '{term}' not found"
        self._highlight(term)
        snippet = "\n".join(found[:10])
        if len(found)>10:
            snippet += f"\n... ({len(found)} total)"
        return f"🔍 Found {len(found)} matches for '{term}':\n{snippet}"

    def _vw_goto(self, ln: Optional[str]) -> str:
        if not ln: return "❌ Missing line"
        try:
            num = int(ln)
        except:
            return f"❌ Invalid line: {ln}"
        if num<1: return "❌ Line > 0"
        idx = f"{num}.0"
        self.file_text.mark_set("insert", idx)
        self.file_text.see(idx)
        self.file_text.tag_delete("curr_line")
        self.file_text.tag_add("curr_line", idx, f"{num}.end")
        self.file_text.tag_config("curr_line", background="#404040")
        return f"✅ Jumped to line {num}"

    def _vw_info(self) -> str:
        c = self.file_text.get("1.0","end-1c")
        if not c:
            return "📄 Viewer empty"
        lines=len(c.splitlines())
        words=len(c.split())
        chars=len(c)
        pos = self.file_text.index("insert")
        return f"📄 {lines} lines, {words} words, {chars} chars\n📍 Cursor at {pos}"

    # -------------------------------------------------------------------------
    # GUI HELPERS
    # -------------------------------------------------------------------------
    def _update_viewer(self, path: str, content: str):
        self.file_text.delete("1.0","end")
        self.file_text.insert("1.0", content)
        self.current_file_label.config(text=f"📄 {os.path.basename(path)}")

    def _highlight(self, term: str):
        self.file_text.tag_delete("hl")
        start="1.0"
        while True:
            pos = self.file_text.search(term, start, stopindex="end", nocase=True)
            if not pos: break
            end = f"{pos}+{len(term)}c"
            self.file_text.tag_add("hl", pos, end)
            start = end
        self.file_text.tag_config("hl", background="#ff0", foreground="#000")

    def open_web_relay(self, agent_id: str):
        """Spuštění relay skriptu pro A1 / A3"""
        info = self.agents_map[agent_id]
        if self.relay_manager.has_relay(agent_id):
            self.relay_manager.remove_relay(agent_id)
            lbl = self.status_labels[self.agents.index(agent_id)]
            lbl.config(text=f"{agent_id}: Offline", foreground="gray")
            self._display("Relay", f"🔌 {info['name']} stopped", self.api_view)
            return

        try:
            self.relay_manager.create_relay(agent_id)
            script = {
                "A1": "web_copilot_launcher.py",
                "A3": "web_claude_launcher.py"
            }.get(agent_id)
            if script:
                subprocess.Popen([sys.executable, script])
            lbl = self.status_labels[self.agents.index(agent_id)]
            lbl.config(text=f"{agent_id}: Running", foreground="#0f0")
            self._display("Relay", f"🚀 {info['name']} started", self.api_view)
        except Exception as e:
            self._display("System", f"❌ relay launch error: {e}", self.api_view)

    def send_via_relay(self, agent_id: str, content: str):
        try:
            ok = self.relay_manager.send_to_agent(agent_id, content)
            tag = "Relay"
            msg = f"{'✅' if ok else '❌'} to {agent_id}: {content[:50]}"
            self._display(tag, msg, self.api_view)
        except Exception as e:
            self._display("System", f"❌ relay send error: {e}", self.api_view)

    def send_to_team_from_input(self):
        t = self.team_input.get("1.0","end-1c").strip()
        if not t: return
        self.send_to_team(t)
        self.team_input.delete("1.0","end")

    def send_to_team(self, text: str):
        ts = datetime.now().isoformat()
        self._display("You", text, self.team_view)
        base = self.active_chat_id.get()
        if not base:
            now = datetime.now()
            base = f"team-{now:%d%m}-{now:%H%M}"
            self.active_chat_id.set(base)
        entry = {"id":f"{base}-{len(self.wip_chats.get(base,[]))+1}",
                 "time":ts,"author":"You","text":text}
        self.wip_chats.setdefault(base,[]).append(entry)
        with open(self.wip_path,'w',encoding='utf-8') as f:
            json.dump(self.wip_chats, f, indent=2, ensure_ascii=False)

        for i,a in enumerate(self.agents):
            if self.recipient_vars[i].get() and self.relay_manager.has_relay(a):
                self.send_via_relay(a, text)

    def open_file_in_viewer(self, path: str):
        try:
            with open(path,'r',encoding='utf-8') as f:
                cnt = f.read()
            self._update_viewer(path, cnt)
        except UnicodeDecodeError:
            self._display("System", f"❌ binary file: {path}", self.api_view)
        except Exception as e:
            self._display("System", f"❌ open error: {e}", self.api_view)

    def send_to_api(self):
        txt = self.api_input.get("1.0","end-1c").strip()
        if not txt: return
        self.api_input.delete("1.0","end")
        self._display("You", txt, self.api_view)
        if not self.gemini:
            self._display("System","❌ Gemini not configured",self.api_view)
            return
        try:
            ctx = self._gemini_context()
            prompt = f"{ctx}\n\nUser: {txt}"
            resp = self.gemini.generate_content(prompt)
            self._display("Gemini", resp.text, self.api_view)
        except Exception as e:
            self._display("System", f"❌ API error: {e}", self.api_view)

    def _gemini_context(self) -> str:
        return """You are an AI with file-manager:
Commands:
- /fm_list [path]
- /fm_read filepath
- /fm_write filepath content
- /fm_create filepath
- /fm_delete filepath
- /fm_mkdir dirpath

Viewer:
- /view_open filepath
- /view_search term
- /view_goto line_number
- /view_info"""

    def _display(self, author: str, msg: str, widget):
        ts = datetime.now().strftime("%H:%M:%S")
        widget.insert("end", f"[{ts}] {author}: {msg}\n")
        widget.see("end")

    def on_closing(self):
        self.relay_manager.stop_monitoring()
        for a in list(self.relay_manager.relays):
            self.relay_manager.remove_relay(a)
        with open(self.wip_path,'w',encoding='utf-8') as f:
            json.dump(self.wip_chats, f, indent=2, ensure_ascii=False)
        self.root.destroy()

relay_manager = RelayManager()
# =============================================================================
# MAIN EXECUTION
# =============================================================================

if __name__ == "__main__":
    try:
        import tkinter.simpledialog
        root = tk.Tk()
        app  = AiCodeBoxApp(root)
        root.mainloop()
    except ImportError as e:
        print(f"Missing dependency: {e}")
        print("pip install google-generativeai")
    except Exception as e:
        print(f"App error: {e}")
        import traceback; traceback.print_exc()

