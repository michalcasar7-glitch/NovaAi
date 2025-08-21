# -*- coding: utf-8 -*-
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox, simpledialog
import os, sys, json, subprocess, threading, shutil, difflib, re, importlib.util
from datetime import datetime
import socket
from PIL import Image, ImageTk, ImageGrab
from dotenv import load_dotenv
import google.generativeai as genai
import requests
from bs4 import BeautifulSoup

# Knihovny pro pokročilé funkce
try:
    import psutil
except ImportError:
    psutil = None
try:
    import mss
except ImportError:
    mss = None

load_dotenv()

# --- Globální konstanty ---
BG_COLOR = '#1e1e1e'
PANEL_BG = '#2d2d2d'
ACCENT_COLOR = '#00ffff'
FONT_FAMILY = "Consolas"
SETTINGS_FILE = 'settings.json'
MEMORY_DIR = 'memory'
HISTORY_FILE = os.path.join(MEMORY_DIR, 'box_history.json')

# --- Třídy pro komunikaci a základní UI ---
class SimpleMessage:
    def __init__(self, agent_id, content, direction, msg_type="chat", msg_id=None, metadata=None):
        self.agent_id, self.content, self.direction = agent_id, content, direction
        self.timestamp, self.msg_id = datetime.now().isoformat(), msg_id
        self.metadata = metadata or {}
        self.metadata['type'] = msg_type
    def to_json(self): return json.dumps(self.__dict__, ensure_ascii=False)
    @classmethod
    def from_json(cls, json_str):
        data = json.loads(json_str)
        instance = cls(data.get('agent_id'), data.get('content'), data.get('direction'))
        instance.__dict__.update(data)
        return instance

class BridgeClient:
    def __init__(self, host='localhost', port=9999):
        self.host, self.port, self.socket, self.connected, self.running, self.callbacks = host, port, None, False, False, []
    def connect(self):
        if self.connected: return True
        try:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.settimeout(2)
            self.socket.connect((self.host, self.port))
            self.socket.settimeout(None)
            self.connected, self.running = True, True
            threading.Thread(target=self._listen_for_messages, daemon=True).start()
            return True
        except: 
            return False
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
                        for callback in self.callbacks:
                            try:
                                # Použijeme root.after_idle bezpečně
                                if hasattr(self, '_root_ref') and self._root_ref:
                                    self._root_ref.after_idle(callback, SimpleMessage.from_json(line))
                            except:
                                pass
            except: 
                break
        self.connected = False
        if self.callbacks and hasattr(self, '_root_ref') and self._root_ref:
            try:
                self._root_ref.after_idle(lambda: self.callbacks[0](SimpleMessage('System', {'manager': ('Offline', 'red')}, 'incoming', msg_type='status_update')))
            except:
                pass
    def send_message(self, message: SimpleMessage):
        if not self.connected: return False
        try: 
            self.socket.sendall((message.to_json() + '\n').encode('utf-8'))
            return True
        except: 
            return False
    def add_callback(self, callback):
        if callback not in self.callbacks: self.callbacks.append(callback)
    def set_root_ref(self, root):
        self._root_ref = root
    def stop(self):
        self.running = False
        if self.socket: 
            try:
                self.socket.close()
            except:
                pass

class TextLineNumbers(tk.Canvas):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.textwidget = None
    def attach(self, text_widget):
        self.textwidget = text_widget
        self.redraw()
    def redraw(self, *args):
        self.delete("all")
        if not self.textwidget: return
        try:
            i = self.textwidget.index("@0,0")
            while True:
                dline = self.textwidget.dlineinfo(i)
                if dline is None: break
                y = dline[1]
                linenum = str(i).split(".")[0]
                self.create_text(2, y, anchor="nw", text=linenum, fill="#6c757d")
                i = self.textwidget.index(f"{i}+1line")
        except:
            pass

class CustomText(tk.Text):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._orig = self._w + "_orig"
        self.tk.call("rename", self._w, self._orig)
        self.tk.createcommand(self._w, self._proxy)
    def _proxy(self, *args):
        try:
            cmd = (self._orig,) + args
            result = self.tk.call(cmd)
            if (args[0] in ("insert", "delete", "replace") or 
                args[0:3] == ("mark", "set", "insert") or 
                args[0:2] == ("xview", "scroll") or 
                args[0:2] == ("yview", "scroll")):
                self.event_generate("<<Change>>", when="tail")
            return result
        except:
            return None

class FilesPanel:
    def __init__(self, parent_app, parent_frame, callback=None):
        self.app = parent_app
        self.callback = callback
        self.current_dir = os.getcwd()
        self.frame = ttk.Frame(parent_frame)
        
        toolbar = ttk.Frame(self.frame)
        toolbar.pack(fill="x", padx=5, pady=2)
        
        buttons = {"🏠": "Domů", "↑": "Nahoru", "🔄": "Obnovit", "➕📁": "Nová složka", 
                  "➕📄": "Nový soubor", "✂️": "Kopírovat", "❌": "Smazat"}
        commands = [self.go_home, self.go_up, self.refresh, self.new_folder, 
                   self.new_file, self.copy_item, self.delete_item]
        
        for (icon, tooltip), command in zip(buttons.items(), commands):
            btn = ttk.Button(toolbar, text=icon, command=command, width=3)
            btn.pack(side="left")
            self.create_tooltip(btn, tooltip)
            
        self.paste_button = ttk.Button(toolbar, text="📋", command=self.paste_item, width=3, state="disabled")
        self.paste_button.pack(side="left")
        self.create_tooltip(self.paste_button, "Vložit")
        
        self.dir_label = ttk.Label(self.frame, text=self.current_dir, foreground=ACCENT_COLOR)
        self.dir_label.pack(fill="x", padx=5, pady=(0,5))
        
        tree_frame = ttk.Frame(self.frame)
        tree_frame.pack(fill="both", expand=True, padx=5, pady=5)
        
        self.tree = ttk.Treeview(tree_frame, columns=("modified", "size"), height=15)
        self.tree.pack(side="left", fill="both", expand=True)
        
        self.tree.heading("#0", text="Název")
        self.tree.heading("modified", text="Datum změny")
        self.tree.heading("size", text="Velikost")
        
        self.tree.column("#0", stretch=tk.YES, minwidth=150)
        self.tree.column("modified", width=120, anchor='center')
        self.tree.column("size", width=80, anchor='e')
        
        self.tree.tag_configure('folder', foreground='#77b3d1')
        self.tree.tag_configure('code', foreground='#c586c0')
        self.tree.tag_configure('image', foreground='#d1a077')
        self.tree.tag_configure('system', font=(FONT_FAMILY, 10, 'bold'))
        
        sb = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        
        self.tree.bind("<Double-Button-1>", self.on_double_click)
        self.tree.bind("<Button-3>", self.show_context_menu)
        self.tree.bind("<F2>", self.rename_item_event)
        self.refresh()
        
    def create_tooltip(self, widget, text):
        tooltip = Tooltip(widget, text)
        widget.bind("<Enter>", lambda e: tooltip.showtip())
        widget.bind("<Leave>", lambda e: tooltip.hidetip())
        
    def show_context_menu(self, event):
        try:
            item_id = self.tree.identify_row(event.y)
            if not item_id: return
            self.tree.selection_set(item_id)
            
            menu = tk.Menu(self.frame, tearoff=0, bg=PANEL_BG, fg=ACCENT_COLOR)
            menu.add_command(label="Otevřít", command=lambda: self.on_double_click(None))
            menu.add_command(label="Přejmenovat (F2)", command=self.rename_item)
            menu.add_command(label="Zálohuj a Edituj", command=self.backup_and_edit)
            menu.add_separator()
            menu.add_command(label="📎 Kopírovat cestu", command=self.copy_path)
            menu.add_command(label="📄 Kopírovat obsah", command=self.copy_content)
            menu.add_separator()
            
            new_file_menu = tk.Menu(menu, tearoff=0, bg=PANEL_BG, fg=ACCENT_COLOR)
            new_file_menu.add_command(label="Python soubor (.py)", command=lambda: self.new_file(ext=".py"))
            new_file_menu.add_command(label="Textový soubor (.txt)", command=lambda: self.new_file(ext=".txt"))
            new_file_menu.add_command(label="JSON soubor (.json)", command=lambda: self.new_file(ext=".json"))
            menu.add_cascade(label="Nový soubor", menu=new_file_menu)
            menu.add_separator()
            menu.add_command(label="❌ Smazat", command=self.delete_item)
            
            menu.post(event.x_root, event.y_root)
        except Exception as e:
            print(f"Chyba context menu: {e}")
            
    def backup_and_edit(self):
        try:
            selected_item = self.tree.selection()
            if not selected_item: return
            
            item_text = self.tree.item(selected_item[0])['text'].strip().split(' ', 2)[-1]
            item_path = os.path.join(self.current_dir, item_text)
            
            if os.path.isfile(item_path):
                shutil.copyfile(item_path, item_path + '.bak')
                self.app._update_status_banner(f"Vytvořena záloha: {os.path.basename(item_path)}.bak")
                if self.callback:
                    self.callback(item_path)
        except Exception as e:
            self.app._update_status_banner(f"❌ Chyba při zálohování: {e}")
            
    def rename_item_event(self, event): 
        self.rename_item()
        
    def rename_item(self):
        try:
            selected_item = self.tree.selection()
            if not selected_item: return
            
            item_text = self.tree.item(selected_item[0])['text'].strip().split(' ', 2)[-1]
            item_path = os.path.join(self.current_dir, item_text)
            old_name = os.path.basename(item_path)
            
            new_name = simpledialog.askstring("Přejmenovat", f"Nový název pro '{old_name}':", initialvalue=old_name)
            if new_name and new_name != old_name:
                new_path = os.path.join(os.path.dirname(item_path), new_name)
                os.rename(item_path, new_path)
                self.app._update_status_banner(f"✅ Přejmenováno na '{new_name}'")
                self.refresh()
        except Exception as e:
            self.app._update_status_banner(f"❌ Chyba při přejmenování: {e}")
            
    def copy_path(self):
        try:
            selected_item = self.tree.selection()
            if not selected_item: return
            
            item_text = self.tree.item(selected_item[0])['text'].strip().split(' ', 2)[-1]
            item_path = os.path.join(self.current_dir, item_text)
            
            self.app.root.clipboard_clear()
            self.app.root.clipboard_append(item_path)
            self.app._update_status_banner(f"📋 Cesta zkopírována do schránky.")
        except Exception as e:
            self.app._update_status_banner(f"❌ Chyba při kopírování cesty: {e}")
            
    def copy_content(self):
        try:
            selected_item = self.tree.selection()
            if not selected_item: return
            
            item_text = self.tree.item(selected_item[0])['text'].strip().split(' ', 2)[-1]
            item_path = os.path.join(self.current_dir, item_text)
            
            if os.path.isfile(item_path):
                with open(item_path, 'r', encoding='utf-8', errors='ignore') as f: 
                    content = f.read()
                self.app.root.clipboard_clear()
                self.app.root.clipboard_append(content)
                self.app._update_status_banner(f"📋 Obsah souboru zkopírován.")
            else:
                self.app._update_status_banner(f"Nelze kopírovat obsah složky.")
        except Exception as e:
            self.app._update_status_banner(f"❌ Chyba při čtení souboru: {e}")
            
    def go_home(self):
        try:
            project_root = os.path.dirname(os.path.abspath(sys.argv[0]))
            self.refresh(project_root)
            main_script_path = os.path.join(project_root, 'ai_codebox_app.py')
            if os.path.exists(main_script_path) and self.callback: 
                self.callback(main_script_path)
        except Exception as e:
            self.app._update_status_banner(f"❌ Chyba při přechodu domů: {e}")
            
    def delete_item(self):
        try:
            selected_item = self.tree.selection()
            if not selected_item: 
                self.app._update_status_banner("❌ Nebyl vybrán žádný soubor nebo složka k odstranění.")
                return
                
            item_text = self.tree.item(selected_item[0])['text'].strip().split(' ', 2)[-1]
            item_path = os.path.join(self.current_dir, item_text)
            item_name = os.path.basename(item_path)
            
            if messagebox.askyesno("Potvrdit smazání", f"Opravdu chcete smazat '{item_name}'? Tato akce je nevratná."):
                if os.path.isdir(item_path): 
                    shutil.rmtree(item_path)
                else: 
                    os.remove(item_path)
                self.app._update_status_banner(f"✅ '{item_name}' bylo smazáno.")
                self.refresh()
        except Exception as e: 
            self.app._update_status_banner(f"❌ Chyba při mazání: {e}")
            
    def copy_item(self):
        try:
            selected_item = self.tree.selection()
            if not selected_item: 
                self.app._update_status_banner("❌ Nebyl vybrán žádný soubor nebo složka ke kopírování.")
                return
                
            item_text = self.tree.item(selected_item[0])['text'].strip().split(' ', 2)[-1]
            self.app.clipboard_path = os.path.join(self.current_dir, item_text)
            self.paste_button.config(state="normal")
            self.app._update_status_banner(f"📋 Zkopírováno: {os.path.basename(self.app.clipboard_path)}")
        except Exception as e:
            self.app._update_status_banner(f"❌ Chyba při kopírování: {e}")
            
    def paste_item(self):
        try:
            if not hasattr(self.app, 'clipboard_path') or not self.app.clipboard_path: 
                self.app._update_status_banner("❌ Schránka je prázdná.")
                return
                
            source_path = self.app.clipboard_path
            dest_path = os.path.join(self.current_dir, os.path.basename(source_path))
            
            if source_path == dest_path: 
                self.app._update_status_banner("Nelze vložit položku na stejné místo.")
                return
                
            if os.path.isdir(source_path): 
                shutil.copytree(source_path, dest_path)
            else: 
                shutil.copy2(source_path, dest_path)
            self.app._update_status_banner(f"✅ Vloženo: {os.path.basename(dest_path)}")
            self.refresh()
        except Exception as e: 
            self.app._update_status_banner(f"❌ Chyba při vkládání: {e}")
            
    def refresh(self, path=None):
        try:
            target_path = path if path else self.current_dir
            if not os.path.exists(target_path) or not os.path.isdir(target_path): 
                return
                
            self.current_dir = target_path
            self.tree.delete(*self.tree.get_children())
            self.dir_label.config(text=self.current_dir)
            
            items = sorted(os.listdir(self.current_dir), 
                         key=lambda x: (not os.path.isdir(os.path.join(target_path, x)), x.lower()))
            
            for i in items:
                full_path = os.path.join(self.current_dir, i)
                tags, icon, size, mod_time = [], "", "", ""
                is_dir = os.path.isdir(full_path)
                is_sys = i in self.app.system_files
                
                if is_dir:
                    tags.append('folder')
                    icon = "📁"
                else:
                    ext = os.path.splitext(i)[1].lower()
                    if ext in ['.py', '.json', '.txt', '.bat', '.csv']: 
                        tags.append('code')
                    elif ext in ['.png', '.jpg', '.jpeg', '.gif', '.bmp']: 
                        tags.append('image')
                    icon = "📄"
                    try: 
                        size = f"{os.path.getsize(full_path) / 1024:.1f} KB"
                    except: 
                        pass
                        
                if is_sys:
                    tags.append('system')
                    icon = f"⚙️ {icon}"
                    
                try: 
                    mod_time = datetime.fromtimestamp(os.path.getmtime(full_path)).strftime('%Y-%m-%d %H:%M')
                except: 
                    pass
                    
                self.tree.insert("", "end", text=f" {icon} {i}", 
                               values=(mod_time, size), tags=tuple(tags))
        except PermissionError: 
            self.tree.insert("", "end", text="❌ Access Denied", values=("", "", ""))
        except Exception as e:
            print(f"Chyba při refresh: {e}")
            
    def go_up(self): 
        try:
            parent = os.path.dirname(self.current_dir)
            if parent != self.current_dir:
                self.refresh(parent)
        except Exception as e:
            self.app._update_status_banner(f"❌ Chyba při přechodu nahoru: {e}")
            
    def on_double_click(self, e):
        try:
            sel = self.tree.selection()
            if not sel: return
            
            item = self.tree.item(sel[0])
            item_text = item['text'].strip().split(' ', 2)[-1]
            path = os.path.join(self.current_dir, item_text)
            
            if 'folder' in item['tags']: 
                self.refresh(path)
            elif self.callback: 
                self.callback(path)
        except Exception as e:
            self.app._update_status_banner(f"❌ Chyba při otevírání: {e}")
            
    def new_folder(self):
        try:
            name = simpledialog.askstring("New Folder","Folder name:")
            if name:
                os.makedirs(os.path.join(self.current_dir,name), exist_ok=True)
                self.refresh()
        except Exception as e: 
            messagebox.showerror("Error", f"Cannot create folder: {e}")
            
    def new_file(self, ext=".txt"):
        try:
            name = simpledialog.askstring("New File",f"File name (bez {ext}):")
            if name:
                path = os.path.join(self.current_dir, name + ext)
                open(path,'w').close()
                self.refresh()
                if self.callback:
                    self.callback(path)
        except Exception as e: 
            messagebox.showerror("Error", f"Cannot create file: {e}")

class Tooltip:
    def __init__(self, widget, text):
        self.widget, self.text, self.tipwindow = widget, text, None
    def showtip(self):
        try:
            if self.tipwindow or not self.text: return
            x, y, _, _ = self.widget.bbox("insert")
            x = x + self.widget.winfo_rootx() + 25
            y = y + self.widget.winfo_rooty() + 25
            self.tipwindow = tw = tk.Toplevel(self.widget)
            tw.wm_overrideredirect(1)
            tw.wm_geometry(f"+{x}+{y}")
            tk.Label(tw, text=self.text, justify=tk.LEFT, 
                    background="#3c3c3c", foreground="white", 
                    relief=tk.SOLID, borderwidth=1, 
                    font=(FONT_FAMILY, 8, "normal")).pack(ipadx=1)
        except:
            pass
    def hidetip(self):
        tw = self.tipwindow
        self.tipwindow = None
        if tw: 
            try:
                tw.destroy()
            except:
                pass

class PluginManager:
    def __init__(self, app_instance, plugin_folder='plugins'):
        self.app = app_instance
        self.plugin_folder = plugin_folder
        self.plugins = {}
        self.load_plugins()
        
    def load_plugins(self):
        self.plugins = {}
        if not os.path.exists(self.plugin_folder): 
            return
            
        try:
            for plugin_name in os.listdir(self.plugin_folder):
                plugin_path = os.path.join(self.plugin_folder, plugin_name)
                if os.path.isdir(plugin_path):
                    json_path = os.path.join(plugin_path, 'plugin.json')
                    py_path = os.path.join(plugin_path, '__init__.py')
                    
                    if os.path.exists(json_path) and os.path.exists(py_path):
                        try:
                            with open(json_path, 'r', encoding='utf-8') as f: 
                                meta = json.load(f)
                            spec = importlib.util.spec_from_file_location(plugin_name, py_path)
                            module = importlib.util.module_from_spec(spec)
                            spec.loader.exec_module(module)
                            
                            command_name = meta.get('command')
                            if command_name and hasattr(module, 'execute'):
                                self.plugins[command_name] = {'meta': meta, 'execute': module.execute}
                                self.app._update_status_banner(f"✅ Plugin '{command_name}' načten.", speak_this_message=False)
                        except Exception as e:
                            error_message = f"❌ Chyba při načítání pluginu '{plugin_name}': {e}"
                            print(error_message) 
                            self.app._update_status_banner(error_message, speak_this_message=False)
        except Exception as e:
            print(f"Chyba při načítání pluginů: {e}")
            
    def execute_command(self, command_name, params):
        try:
            plugin = self.plugins.get(command_name)
            if plugin:
                result_message = plugin['execute'](self.app.api, params)
                if result_message: 
                    self.app._update_status_banner(result_message)
            else: 
                self.app._update_status_banner(f"Neznámý příkaz/plugin: {command_name}")
        except Exception as e: 
            self.app._update_status_banner(f"❌ Chyba pluginu '{command_name}': {e}")

class AppAPI:
    def __init__(self, app_instance):
        self.app = app_instance
        
    def write_file(self, path, content, backup=False):
        try:
            old_content = ""
            if os.path.exists(path):
                try:
                    with open(path, 'r', encoding='utf-8', errors='ignore') as f_old: 
                        old_content = f_old.read()
                except Exception: 
                    pass
                    
            if backup and os.path.exists(path): 
                shutil.copyfile(path, path + '.bak')
                self.app._update_status_banner(f"Vytvořena záloha: {path}.bak")
                
            dir_name = os.path.dirname(path)
            if dir_name: 
                os.makedirs(dir_name, exist_ok=True)
                
            with open(path, 'w', encoding='utf-8') as f: 
                f.write(content)
            self.app._update_status_banner(f"✅ Soubor '{path}' byl zapsán.")
            
            if hasattr(self.app, 'files_panel'):
                self.app.files_panel.refresh(os.path.dirname(path) if os.path.dirname(path) else None)
            self.app.show_diff_view(path, old_text=old_content, new_text=content)
        except Exception as e: 
            self.app._update_status_banner(f"❌ Chyba při zápisu do souboru {path}: {e}")
            
    def find_and_replace(self, path, find_string, replace_string, backup=True):
        try:
            with open(path, 'r', encoding='utf-8') as f: 
                old_content = f.read()
                
            if find_string not in old_content: 
                self.app._update_status_banner(f"Chyba: Text k nahrazení nebyl v souboru '{path}' nalezen.")
                return
                
            if backup: 
                shutil.copyfile(path, path + '.bak')
                self.app._update_status_banner(f"Vytvořena záloha: {path}.bak")
                
            new_content = old_content.replace(find_string, replace_string)
            
            with open(path, 'w', encoding='utf-8') as f: 
                f.write(new_content)
            self.app._update_status_banner(f"✅ Soubor '{path}' byl úspěšně upraven.")
            self.app.show_diff_view(path, old_text=old_content, new_text=new_content)
        except Exception as e: 
            self.app._update_status_banner(f"❌ Chyba při úpravě souboru {path}: {e}")
            
    def google_search(self, query):
        try:
            self.app._update_status_banner(f"Vyhledávám: '{query}'...")
            headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
            res = requests.get(f'https://www.google.com/search?q={query}', headers=headers)
            res.raise_for_status()
            
            soup = BeautifulSoup(res.text, 'html.parser')
            results, summary = [], f"Výsledky hledání pro '{query}':\n"
            
            for g in soup.find_all('div', class_='g'):
                anchors = g.find_all('a')
                if anchors:
                    link = anchors[0]['href']
                    title = g.find('h3').text if g.find('h3') else 'N/A'
                    results.append({'title': title, 'link': link})
                    
            if not results:
                summary += "Nebyly nalezeny žádné výsledky."
            else:
                summary += "\n".join([f"- {r['title']}: {r['link']}" for r in results[:5]])
                
            self.app._display("System", summary, self.app.api_view, "system_message")
        except Exception as e:
            self.app._update_status_banner(f"❌ Chyba při vyhledávání: {e}")
            
    def read_file(self, path):
        try:
            with open(path, 'r', encoding='utf-8', errors='ignore') as f: 
                content = f.read()
            self.app._display("System", f"--- OBSAH SOUBORU: {path} ---\n{content}", self.app.api_view, "system_message")
        except Exception as e: 
            self.app._update_status_banner(f"❌ Chyba při čtení souboru {path}: {e}")
            
    def list_files(self, path=None): 
        if hasattr(self.app, 'files_panel'):
            self.app.files_panel.refresh(os.path.abspath(path) if path else None)
            self.app._update_status_banner(f"Zobrazen obsah: {path or self.app.files_panel.current_dir}")
        
    def open_file(self, path): 
        self.app.open_file_in_viewer(path)
        
    def create_folder(self, path):
        try: 
            os.makedirs(path, exist_ok=True)
            self.app._update_status_banner(f"✅ Složka '{path}' byla vytvořena.")
            if hasattr(self.app, 'files_panel'):
                self.app.files_panel.refresh()
        except Exception as e: 
            self.app._update_status_banner(f"❌ Chyba při vytváření složky: {e}")
            
    def save_file(self): 
        self.app._save_current_file()
        
    def execute_command(self, command_line): 
        self.app._execute_command_async(command_line)
        
    def reboot_codebox(self): 
        self.app._reboot_codebox()
        
    def launch_test_relay(self, url=None): 
        self.app.launch_debug_relay(url=url)
        
    def save_relay_profile(self, profile_name=None): 
        self.app.save_debug_profile(profile_name=profile_name)
        
    def take_screenshot(self, mode='fullscreen'): 
        self.app.take_screenshot(mode)
        
    def get_pixel_color(self, path, x, y):
        try:
            with Image.open(path) as img:
                rgb_im = img.convert('RGB')
                r, g, b = rgb_im.getpixel((int(x), int(y)))
                hex_color = f'#{r:02x}{g:02x}{b:02x}'
                self.app._update_status_banner(f"Barva na [{x},{y}] v '{os.path.basename(path)}' je {hex_color}")
        except Exception as e: 
            self.app._update_status_banner(f"❌ Chyba při analýze obrázku: {e}")

class AiCodeBoxApp:
    def __init__(self, root):
        self.root = root
        self.root.title("AI Code Box")
        self.root.geometry("1600x900")
        
        # Bezpečné načtení pozadí
        try:
            bg_image_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "background.jpg")
            if os.path.exists(bg_image_path):
                bg_image = Image.open(bg_image_path)
                self.bg_photo = ImageTk.PhotoImage(bg_image)
                tk.Label(root, image=self.bg_photo).place(x=0, y=0, relwidth=1, relheight=1)
            else:
                self.root.configure(bg=BG_COLOR)
        except Exception as e: 
            print(f"Chyba načtení pozadí: {e}")
            self.root.configure(bg=BG_COLOR)
        
        # Inicializace proměnných
        self.clipboard_path = None
        self.current_file_path = None
        self.viewer_diff_mode = False
        self.viewer_image_photo = None
        self.system_files = self._scan_for_system_files()
        self.system_statuses = {'manager': ('Unknown', 'grey'), 'gemini': ('Unknown', 'grey')}
        
        # Inicializace komponent
        self.bridge_client = BridgeClient()
        self.bridge_client.set_root_ref(root)
        self.bridge_client.add_callback(self._handle_bridge_message)
        
        self.gemini = None
        self.gemini_system_prompt = ""
        self.api = AppAPI(self)
        
        self.status_indicators = {}
        self.agent_buttons = {}
        
        # Načtení nastavení
        self._load_settings()
        
        # Nastavení stylů a GUI
        self._setup_styles()
        self._setup_gui()
        
        # Inicializace pluginů
        self.plugin_manager = PluginManager(self)
        
        # Nastavení Gemini
        self._setup_gemini()
        
        # Plánované úkoly
        self.root.after(1000, self.connect_or_launch_manager)
        self.root.after(2000, self.load_manifest_and_init_gemini)
        
        # Ošetření uzavření okna
        self.root.protocol("WM_DELETE_WINDOW", self.shutdown_full_system)

    def _setup_gemini(self):
        try:
            api_key = os.getenv('GOOGLE_API_KEY')
            if api_key:
                genai.configure(api_key=api_key)
                self.gemini = genai.GenerativeModel('gemini-2.5-flash')
                self.system_statuses['gemini'] = ('Online', 'green')
                self._update_status_banner("✅ Gemini API inicializováno.")
            else:
                self.system_statuses['gemini'] = ('No API Key', 'orange')
                self._update_status_banner("⚠️ Gemini API klíč nenalezen v .env souboru.")
        except Exception as e:
            self.system_statuses['gemini'] = ('Error', 'red')
            self._update_status_banner(f"❌ Chyba inicializace Gemini: {e}")
        
        # Aktualizace UI
        if hasattr(self, 'status_indicators_frame'):
            self._update_dynamic_ui()

    def _scan_for_system_files(self):
        try:
            with open(sys.argv[0], 'r', encoding='utf-8') as f: 
                content = f.read()
            return {os.path.basename(f) for f in re.findall(r'["\']([^"\']*\.[^"\']*)["\']', content)}
        except Exception as e: 
            print(f"Chyba při skenování systémových souborů: {e}")
            return set()
        
    def _load_settings(self):
        try:
            with open(SETTINGS_FILE, 'r') as f: 
                settings = json.load(f)
            self.read_status_aloud = tk.BooleanVar(value=settings.get('read_status_aloud', False))
            self.live_mode_enabled = tk.BooleanVar(value=settings.get('live_mode_enabled', False))
        except (FileNotFoundError, json.JSONDecodeError):
            self.read_status_aloud = tk.BooleanVar(value=False)
            self.live_mode_enabled = tk.BooleanVar(value=False)

    def _save_settings(self):
        try:
            settings = {
                'read_status_aloud': self.read_status_aloud.get(),
                'live_mode_enabled': self.live_mode_enabled.get()
            }
            with open(SETTINGS_FILE, 'w') as f: 
                json.dump(settings, f, indent=2)
            self._update_status_banner("Nastavení uloženo.")
            self._update_live_mode_button_style()
        except Exception as e:
            self._update_status_banner(f"❌ Chyba při ukládání nastavení: {e}")
        
    def _setup_styles(self):
        try:
            style = ttk.Style()
            style.theme_use('clam')
            
            style.configure('.', background=BG_COLOR, foreground=ACCENT_COLOR, font=(FONT_FAMILY, 10))
            style.configure('TFrame', background=BG_COLOR)
            style.configure('Transparent.TFrame', background=BG_COLOR)
            style.configure('TLabel', background=BG_COLOR, foreground=ACCENT_COLOR)
            style.configure('TButton', background=PANEL_BG, foreground=ACCENT_COLOR, 
                          bordercolor=ACCENT_COLOR, lightcolor=PANEL_BG, darkcolor=PANEL_BG)
            style.map('TButton', background=[('active', ACCENT_COLOR)], foreground=[('active', 'black')])
            style.configure('Treeview', background=PANEL_BG, foreground=ACCENT_COLOR, 
                          fieldbackground=PANEL_BG, bordercolor=ACCENT_COLOR)
            style.configure('Collapsible.TFrame', background=PANEL_BG, relief="solid", 
                          borderwidth=1, bordercolor=ACCENT_COLOR)
            style.configure('Title.TLabel', background=PANEL_BG, font=(FONT_FAMILY, 12, 'bold'))
            style.configure('Debug.TButton', background='#8A2BE2', foreground='white')
            style.map('Debug.TButton', background=[('active', '#9932CC')])
            style.configure('Live.TButton', background='#FF4500', foreground='white')
            style.map('Live.TButton', background=[('active', '#FF6347')])
        except Exception as e:
            print(f"Chyba při nastavování stylů: {e}")
    
    def _setup_gui(self):
        try:
            main = ttk.Frame(self.root, style='Transparent.TFrame')
            main.pack(fill="both", expand=True, padx=10, pady=(150, 10))
            
            main_paned_window = ttk.PanedWindow(main, orient='horizontal')
            main_paned_window.pack(fill='both', expand=True)
            
            # Levý panel - File Manager
            left_side_panel = ttk.Frame(main_paned_window, width=350)
            main_paned_window.add(left_side_panel, weight=25)
            
            # Střední panel
            center_frame = ttk.Frame(main_paned_window)
            main_paned_window.add(center_frame, weight=60)
            
            # Pravý panel
            right_side_panel = ttk.Frame(main_paned_window, width=250)
            main_paned_window.add(right_side_panel, weight=15)

            # Levý panel - File Manager
            ttk.Label(left_side_panel, text="📁 File Manager", font=(FONT_FAMILY, 12, 'bold')).pack(pady=(0,5), padx=5, anchor='w')
            fp_frame = ttk.Frame(left_side_panel, style='Collapsible.TFrame')
            fp_frame.pack(fill="both", expand=True, padx=5, pady=5)
            
            self.files_panel = FilesPanel(self, fp_frame, callback=self.open_file_in_viewer)
            self.files_panel.frame.pack(fill="both", expand=True)
            
            # Střední panel - tři sekce
            center_paned_window = ttk.PanedWindow(center_frame, orient='vertical')
            center_paned_window.pack(fill='both', expand=True)
            
            self.team_comm_frame = ttk.Frame(center_paned_window, style='Collapsible.TFrame')
            center_paned_window.add(self.team_comm_frame, weight=30)
            
            self.file_viewer_frame = ttk.Frame(center_paned_window, style='Collapsible.TFrame')
            center_paned_window.add(self.file_viewer_frame, weight=40)
            
            self.api_chat_frame = ttk.Frame(center_paned_window, style='Collapsible.TFrame')
            center_paned_window.add(self.api_chat_frame, weight=30)
            
            # Hlavičky sekcí
            for frame, title in zip([self.team_comm_frame, self.file_viewer_frame, self.api_chat_frame], 
                                   ["Team Communication", "File Viewer", "API Chat"]):
                title_frame = ttk.Frame(frame, style='Transparent.TFrame')
                title_frame.pack(fill='x', expand=False)
                ttk.Label(title_frame, text=f" {title}", font=(FONT_FAMILY, 12, 'bold'), 
                         style='Title.TLabel').pack(side='left', padx=5, pady=2)
            
            # Team Communication
            self.team_comm_agents_frame = ttk.Frame(self.team_comm_frame)
            self.team_comm_agents_frame.pack(fill="x", pady=5, padx=5)
            
            self.team_view = scrolledtext.ScrolledText(self.team_comm_frame, height=10, bg=PANEL_BG, 
                                                      fg=ACCENT_COLOR, wrap="word", font=(FONT_FAMILY, 10))
            self.team_view.pack(fill="both", expand=True, pady=(0,5), padx=5)
            
            team_input_frame = ttk.Frame(self.team_comm_frame)
            team_input_frame.pack(fill='x', padx=5, pady=5)
            
            self.team_input = tk.Text(team_input_frame, height=3, bg=PANEL_BG, fg=ACCENT_COLOR, 
                                     wrap="word", font=(FONT_FAMILY, 10))
            self.team_input.pack(side="left", fill="x", expand=True)
            
            ttk.Button(team_input_frame, text="Send", command=self.send_to_team_from_input, width=5).pack(side="left", padx=(5,0))
            
            # Konfigurace tagů
            self.team_view.tag_configure("user_message", justify="right", background="#004d40", 
                                        foreground="white", rmargin=10)
            self.team_view.tag_configure("agent_message", justify="left", rmargin=10)
            
            # Binding klávesových zkratek
            self.team_input.bind("<Return>", lambda event: self.handle_send_keypress(event, self.send_to_team_from_input))
            self.team_input.bind("<Shift-Return>", self.handle_newline_keypress)

            # File Viewer
            file_header = ttk.Frame(self.file_viewer_frame)
            file_header.pack(fill="x", padx=5, pady=5)
            
            self.current_file_label = ttk.Label(file_header, text="No file selected", font=(FONT_FAMILY, 10, 'italic'))
            self.current_file_label.pack(side="left")
            
            ttk.Button(file_header, text="💾 Save", command=self.api.save_file).pack(side="right")
            
            self.viewer_content_frame = ttk.Frame(self.file_viewer_frame)
            self.viewer_content_frame.pack(fill="both", expand=True, pady=5, padx=5)
            
            self.linenumbers = TextLineNumbers(self.viewer_content_frame, width=40, bg=PANEL_BG, 
                                             highlightthickness=0, borderwidth=0)
            
            self.file_text = CustomText(self.viewer_content_frame, bg=PANEL_BG, fg=ACCENT_COLOR, 
                                       wrap="none", font=(FONT_FAMILY, 10), 
                                       highlightthickness=0, borderwidth=0)
            
            file_text_scrollbar = ttk.Scrollbar(self.viewer_content_frame, orient="vertical", 
                                               command=self.file_text.yview)
            file_text_scrollbar.pack(side="right", fill="y")
            self.file_text.config(yscrollcommand=file_text_scrollbar.set)
            
            self.linenumbers.attach(self.file_text)
            self.file_text.bind("<<Change>>", self.linenumbers.redraw)
            self.file_text.bind("<Configure>", self.linenumbers.redraw)
            
            # Konfigurace diff tagů
            self.file_text.tag_configure("diff_added", foreground="#4CAF50")
            self.file_text.tag_configure("diff_deleted", foreground="#9e9e9e")
            self.file_text.tag_configure("diff_prefix", foreground="#888888")
            
            self.image_label = ttk.Label(self.viewer_content_frame)
            self.image_label.bind("<Button-3>", self.show_viewer_context_menu)
            self.file_text.bind("<Button-3>", self.show_viewer_context_menu)
            
            # API Chat
            self.api_view = scrolledtext.ScrolledText(self.api_chat_frame, height=10, bg=PANEL_BG, 
                                                     fg=ACCENT_COLOR, wrap="word", font=(FONT_FAMILY, 10))
            self.api_view.pack(fill="both", expand=True, pady=(0,5), padx=5)
            
            api_input_frame = ttk.Frame(self.api_chat_frame)
            api_input_frame.pack(fill='x', padx=5, pady=5)
            
            self.api_input = tk.Text(api_input_frame, height=3, bg=PANEL_BG, fg=ACCENT_COLOR, 
                                    wrap="word", font=(FONT_FAMILY, 10))
            self.api_input.pack(side="left", fill="x", expand=True)
            
            ttk.Button(api_input_frame, text="Send", command=self.send_to_api, width=5).pack(side="left", padx=(5,0))
            
            # Konfigurace API tagů
            self.api_view.tag_configure("user_message", justify="right", background="#004d40", 
                                       foreground="white", rmargin=10)
            self.api_view.tag_configure("agent_message", justify="left", foreground=ACCENT_COLOR, rmargin=10)
            self.api_view.tag_configure("system_message", justify="left", foreground="orange", rmargin=10)
            
            self.api_input.bind("<Return>", lambda event: self.handle_send_keypress(event, self.send_to_api))
            self.api_input.bind("<Shift-Return>", self.handle_newline_keypress)

            # Pravý panel - Status a ovládání
            ttk.Label(right_side_panel, text="📊 Stav Systému", font=(FONT_FAMILY, 12, 'bold')).pack(pady=(0,10), padx=5, anchor='w')
            
            status_controls_frame = ttk.Frame(right_side_panel)
            status_controls_frame.pack(fill='x', padx=5, pady=5)
            
            ttk.Button(status_controls_frame, text="🔄 Restart Code Box", command=self.api.reboot_codebox).pack(fill='x')
            
            self.relay_manager_button = ttk.Button(status_controls_frame, text="⏯️ Zapnout Relay Manager", 
                                                  command=self._toggle_relay_manager_by_api)
            self.relay_manager_button.pack(fill='x', pady=5)
            
            ttk.Separator(status_controls_frame).pack(fill='x', pady=5)
            
            ttk.Button(status_controls_frame, text="📸 Screenshot", command=self.show_screenshot_menu).pack(fill='x')
            
            ttk.Button(status_controls_frame, text="🐞 Spustit Test Mode", 
                      command=lambda: self.api.launch_test_relay(url=None)).pack(fill='x', pady=(5,0))
            
            ttk.Button(status_controls_frame, text="💾 Uložit profil agenta", 
                      command=lambda: self.api.save_relay_profile(profile_name=None)).pack(fill='x', pady=5)
            
            self.debug_button = ttk.Button(status_controls_frame, text="🛠️ Spustit Ladění", 
                                          command=self.toggle_debugging_mode, style='Debug.TButton', state='disabled')
            self.debug_button.pack(fill='x', pady=5)
            
            self.live_mode_button = ttk.Button(status_controls_frame, text="▶️ Zapnout Live Režim", 
                                              command=self.toggle_live_mode)
            self.live_mode_button.pack(fill='x', pady=(10,5))
            self._update_live_mode_button_style()
            
            # Status indikátory
            self.status_indicators_frame = ttk.Frame(right_side_panel)
            self.status_indicators_frame.pack(fill='x', padx=5, pady=5)
            
            ttk.Separator(right_side_panel, orient='horizontal').pack(fill='x', pady=10, padx=5)
            
            # Status banner
            status_banner_frame = ttk.Frame(right_side_panel)
            status_banner_frame.pack(fill='x', padx=5)
            
            ttk.Label(status_banner_frame, text="📋 Poslední zpráva:").pack(side='left', anchor='n')
            
            self.status_banner_label = ttk.Label(right_side_panel, text="Systém se spouští...", 
                                                foreground="orange", wraplength=230, anchor='nw', justify='left')
            self.status_banner_label.pack(fill='x', pady=5, padx=5)
            
            ttk.Separator(right_side_panel, orient='horizontal').pack(fill='x', pady=10, padx=5)
            
            # Bridge status
            ttk.Label(right_side_panel, text="📡 Log z Agenta", font=(FONT_FAMILY, 10, 'bold')).pack(anchor='w', padx=5)
            
            self.bridge_status_label = ttk.Label(right_side_panel, text="Čekám na data...", 
                                                foreground="grey", wraplength=230, anchor='nw', justify='left')
            self.bridge_status_label.pack(fill='x', pady=5, padx=5)
            
            # Tlačítko ukončení
            ttk.Button(right_side_panel, text="🔴 Ukončit Vše", command=self.shutdown_full_system).pack(side='bottom', fill="x", pady=5, padx=5)
            
            # Aktualizace dynamického UI
            self._update_dynamic_ui()
            
        except Exception as e:
            print(f"Chyba při nastavování GUI: {e}")
            messagebox.showerror("Kritická chyba", f"Chyba při vytváření GUI: {e}")

    def handle_send_keypress(self, event, send_function): 
        try:
            send_function()
            return "break"
        except Exception as e:
            self._update_status_banner(f"❌ Chyba při odesílání: {e}")
            return "break"
        
    def handle_newline_keypress(self, event): 
        pass
        
    def _reboot_codebox(self): 
        try:
            self._update_status_banner("Restartuji aplikaci...")
            reboot_script = os.path.join(os.path.dirname(__file__), "reboot.bat")
            if os.path.exists(reboot_script):
                subprocess.Popen([reboot_script], cwd=os.path.dirname(__file__))
            else:
                # Fallback restart
                python = sys.executable
                os.execl(python, python, *sys.argv)
            self.root.destroy()
        except Exception as e:
            self._update_status_banner(f"❌ Chyba při restartu: {e}")
            
    def _execute_command_async(self, command_line):
        def run_command():
            try:
                self._update_status_banner(f"Spouštím příkaz: {command_line}")
                result = subprocess.run(command_line, shell=True, capture_output=True, text=True, timeout=30)
                output = result.stdout + result.stderr
                self.root.after_idle(lambda: self._display("System", f"Příkaz: {command_line}\nVýstup:\n{output}", self.api_view, "system_message"))
                self.root.after_idle(lambda: self._update_status_banner("✅ Příkaz dokončen."))
            except subprocess.TimeoutExpired:
                self.root.after_idle(lambda: self._update_status_banner("❌ Příkaz vypršel (timeout 30s)."))
            except Exception as e:
                self.root.after_idle(lambda: self._update_status_banner(f"❌ Chyba při spouštění příkazu: {e}"))
        
        threading.Thread(target=run_command, daemon=True).start()
        
    def _toggle_relay_manager_by_api(self, state=None):
        try:
            is_online = self.system_statuses.get('manager', ('Offline', 'red'))[0] == 'Online'
            target_on = not is_online if state is None else state
            
            if target_on:
                self.connect_or_launch_manager()
            else:
                self.bridge_client.send_message(SimpleMessage('System', 'shutdown', 'outgoing', msg_type='system_command'))
        except Exception as e:
            self._update_status_banner(f"❌ Chyba při přepínání Relay Manageru: {e}")

    def load_manifest_and_init_gemini(self):
        try:
            os.makedirs(MEMORY_DIR, exist_ok=True)
            manifest_path = os.path.join(os.path.dirname(__file__), "welcome", "nova_codebox_manifest.json")
            
            # Pokud manifest neexistuje, vytvoř základní
            if not os.path.exists(manifest_path):
                os.makedirs(os.path.dirname(manifest_path), exist_ok=True)
                basic_manifest = {
                    "geminiSystemPrompt": [
                        "Jsi 'Gemi-Boss', AI asistent integrovaný v aplikaci AI Code Box.",
                        "Můžeš komunikovat běžně nebo používat JSON příkazy pro ovládání aplikace."
                    ]
                }
                with open(manifest_path, 'w', encoding='utf-8') as f:
                    json.dump(basic_manifest, f, ensure_ascii=False, indent=2)

            with open(manifest_path, 'r', encoding='utf-8') as f: 
                manifest_data = json.load(f)

            # Načtení historie
            history_data = []
            if os.path.exists(HISTORY_FILE):
                try:
                    with open(HISTORY_FILE, 'r', encoding='utf-8') as f: 
                        history_data = json.load(f)
                except (json.JSONDecodeError, FileNotFoundError): 
                    pass 

            # Sestavení system promptu
            prompt_lines = manifest_data.get("geminiSystemPrompt", [])
            if history_data:
                history_prompt = ["\n=== Historie naší minulé konverzace ==="] + [f"- {item.get('author', 'Unknown')}: {item.get('content', '')}" for item in history_data[-10:]]
                self.gemini_system_prompt = "\n".join(prompt_lines + history_prompt)
            else:
                self.gemini_system_prompt = "\n".join(prompt_lines)

            if not self.gemini: 
                self._update_status_banner("⚠️ Gemini není k dispozici.")
                return
            
            # Úvodní zpráva
            plan = manifest_data.get("developmentPlan", [])
            first_task = next((task for task in plan if task.get("status") != "hotovo"), None)
            
            initial_prompt = "Zdravím! Jsem Gemi-Boss, připraven k práci."
            if first_task: 
                initial_prompt += f" Podle plánu je naším dalším úkolem: {first_task.get('title')}."
            
            threading.Thread(target=self._generate_gemini_response, args=(initial_prompt, False), daemon=True).start()
            
        except Exception as e:
            self._update_status_banner(f"❌ Chyba při načítání manifestu: {e}")

    def _generate_gemini_response(self, prompt, is_user_request=False):
        try:
            if not self.gemini:
                self.root.after_idle(lambda: self._update_status_banner("❌ Gemini není k dispozici."))
                return
                
            full_prompt = f"{self.gemini_system_prompt}\n\nUživatel: {prompt}" if is_user_request else f"{self.gemini_system_prompt}\n\n{prompt}"
            response = self.gemini.generate_content(full_prompt)
            
            if response and response.text:
                if is_user_request: 
                    self.root.after_idle(lambda: self._process_gemini_command(response.text))
                else: 
                    self.root.after_idle(lambda: self._display("Gemini-API", response.text, self.api_view, tag="agent_message"))
            else:
                self.root.after_idle(lambda: self._update_status_banner("❌ Gemini nevrátilo odpověď."))
        except Exception as e:
            self.root.after_idle(lambda: self._update_status_banner(f"❌ Chyba komunikace s Gemini: {e}"))
        
    def _process_gemini_command(self, response_text: str):
        try:
            # Vždy nejdříve zobraz odpověď
            self._display("Gemini-API", response_text, self.api_view, tag="agent_message")
            
            # Pokus se najít JSON příkaz v odpovědi
            json_found = False
            start_index = response_text.find('{')
            end_index = response_text.rfind('}')
            
            if start_index != -1 and end_index != -1 and end_index > start_index:
                try:
                    json_text = response_text[start_index : end_index + 1]
                    data = json.loads(json_text)
                    command_name = data.get("command")
                    
                    if command_name:
                        json_found = True
                        params = data.copy()
                        del params['command']
                        
                        # Zkus najít příkaz v API
                        if hasattr(self.api, command_name):
                            getattr(self.api, command_name)(**params)
                            self._update_status_banner(f"✅ Příkaz '{command_name}' dokončen.")
                        elif command_name in self.plugin_manager.plugins:
                            self.plugin_manager.execute_command(command_name, params)
                            self._update_status_banner(f"✅ Plugin '{command_name}' dokončen.")
                        else:
                            self._update_status_banner(f"❌ Neznámý příkaz: {command_name}")
                            
                except json.JSONDecodeError:
                    # JSON je neplatný, ale to je v pořádku
                    pass
                    
            # Pokud nebyl nalezen žádný JSON příkaz, je to běžná konverzace
            if not json_found:
                # Odpověď už je zobrazena, není třeba nic dalšího dělat
                pass
                
        except Exception as e:
            self._update_status_banner(f"❌ Chyba při zpracování odpovědi: {e}")

    def send_to_api(self):
        try:
            txt = self.api_input.get("1.0","end-1c").strip()
            if not txt: return
            
            self.api_input.delete("1.0","end")
            self._display("You", txt, self.api_view, tag="user_message")
            
            # Rychlé příkazy
            USER_COMMANDS = { 
                "pust hudbu": {"command": "run_shortcut", "params": {"shortcut_name": "spotify"}} 
            }
            command_to_run = USER_COMMANDS.get(txt.lower())
            if command_to_run:
                self.plugin_manager.execute_command(command_to_run["command"], command_to_run["params"])
                return
            
            if not self.gemini: 
                self._update_status_banner("❌ Gemini není nakonfigurováno.")
                return
                
            threading.Thread(target=self._generate_gemini_response, args=(txt, True), daemon=True).start()
        except Exception as e:
            self._update_status_banner(f"❌ Chyba při odesílání do API: {e}")
        
    def _handle_bridge_message(self, msg: SimpleMessage):
        try:
            if msg.metadata.get('type') == 'status_update': 
                self.system_statuses.update(msg.content)
                self._update_dynamic_ui()
                return
                
            if msg.metadata.get('type') == 'js_log': 
                self._update_bridge_status(msg.content)
                return
                
            if msg.direction == "incoming": 
                self._display(msg.agent_id, msg.content, self.team_view, tag="agent_message")
        except Exception as e:
            print(f"Chyba při zpracování bridge zprávy: {e}")
    
    def _update_dynamic_ui(self):
        try:
            # Vyčisti stávající status indikátory
            for widget in self.status_indicators_frame.winfo_children(): 
                widget.destroy()
                
            # Vytvoř nové indikátory
            all_components = ['manager', 'gemini'] + sorted([key for key in self.system_statuses if key not in ['manager', 'gemini']])
            
            for key in all_components:
                text, color = self.system_statuses.get(key, ('Unknown', 'grey'))
                frame = ttk.Frame(self.status_indicators_frame)
                frame.pack(fill='x', padx=5, pady=2)
                
                name = key.replace("_", " ").title() if key not in ['manager', 'gemini'] else ('Relay Manager' if key == 'manager' else 'Gemini API')
                ttk.Label(frame, text=f"{name}:").pack(side='left')
                
                label = ttk.Label(frame, text=text, foreground=color, anchor='e')
                label.pack(side='right')
                self.status_indicators[key] = label
            
            # Aktualizuj stav debug tlačítka
            is_test_agent_online = self.system_statuses.get('TestAgent', ('Offline', 'red'))[0] == 'Online'
            if hasattr(self, 'debug_button'): 
                self.debug_button.config(state='normal' if is_test_agent_online else 'disabled')

            # Aktualizuj agent tlačítka v team comm
            for widget in self.team_comm_agents_frame.winfo_children(): 
                widget.destroy()
                
            self.agent_buttons = {}
            buttons_container = ttk.Frame(self.team_comm_agents_frame)
            buttons_container.pack()
            
            permanent_agents = sorted([agent for agent in self.system_statuses if agent not in ['manager', 'gemini', 'TestAgent']])
            for agent_id in permanent_agents:
                frame = ttk.Frame(buttons_container)
                frame.pack(side='left', padx=5)
                
                btn = ttk.Button(frame, text=agent_id, width=4, command=lambda a=agent_id: self.activate_agent_view(a))
                btn.pack(side="left")
                
                var = tk.BooleanVar(value=True)
                ttk.Checkbutton(frame, variable=var).pack(side="right")
                self.agent_buttons[agent_id] = {'button': btn, 'var': var}
            
            # Aktualizuj relay manager tlačítko
            if hasattr(self, 'relay_manager_button'): 
                self._update_relay_manager_button_state()
        except Exception as e:
            print(f"Chyba při aktualizaci UI: {e}")
        
    def _update_relay_manager_button_state(self):
        try:
            if hasattr(self, 'relay_manager_button'):
                status = self.system_statuses.get('manager', ('Unknown', 'grey'))[0]
                self.relay_manager_button.config(text="⏹️ Vypnout Relay Manager" if status == 'Online' else "⏯️ Zapnout Relay Manager")
        except Exception as e:
            print(f"Chyba při aktualizaci relay tlačítka: {e}")
            
    def shutdown_full_system(self): 
        try:
            self.bridge_client.send_message(SimpleMessage('System', 'shutdown', 'outgoing', msg_type='system_command'))
            self.root.after(500, self.on_closing)
        except Exception as e:
            print(f"Chyba při vypínání: {e}")
            self.on_closing()
            
    def on_closing(self): 
        try:
            self.bridge_client.stop()
            self.root.destroy()
        except Exception as e:
            print(f"Chyba při zavírání: {e}")
            
    def send_to_team_from_input(self):
        try:
            content = self.team_input.get("1.0", "end-1c").strip()
            if not content: return
            
            self.team_input.delete("1.0", "end")
            self._display("You", content, self.team_view, tag="user_message")
            
            selected_agents = [agent_id for agent_id, data in self.agent_buttons.items() if data['var'].get()]
            if not selected_agents: 
                self._update_status_banner("❌ Nevybrán žádný agent pro odeslání.")
                return
                
            for agent_id in selected_agents: 
                self.bridge_client.send_message(SimpleMessage(agent_id, content, "outgoing", "chat"))
        except Exception as e:
            self._update_status_banner(f"❌ Chyba při odesílání do týmu: {e}")
    
    def _display(self, author: str, msg: str, widget, tag=None):
        try:
            if len(msg) > 10000: 
                msg = msg[:10000] + "\n\n... (Zpráva byla pro zobrazení zkrácena)"
                
            if tag is None: 
                tag = "user_message" if author == "You" else "agent_message"
                
            final_msg = f"[{datetime.now().strftime('%H:%M:%S')}] {author}:\n{msg}\n\n"
            widget.insert("end", final_msg, tag)
            widget.see("end")
            
            # Uložení historie po každé zprávě
            if widget in [self.api_view, self.team_view]: 
                self._save_history()
        except Exception as e:
            print(f"Chyba při zobrazování zprávy: {e}")

    def _save_history(self):
        try:
            os.makedirs(MEMORY_DIR, exist_ok=True)
            history = []
            
            # Zpracuj obsah z obou chat widgetů
            for widget in [self.api_view, self.team_view]:
                content = widget.get("1.0", "end-1c").strip()
                if content:
                    # Rozdělení na jednotlivé zprávy podle dvojitého odřádkování
                    entries = content.split('\n\n')
                    for entry in entries:
                        entry = entry.strip()
                        if not entry:
                            continue
                        try:
                            # Formát: [HH:MM:SS] Author:\nContent
                            if entry.startswith('[') and ']:' in entry:
                                header_end = entry.find(']:\n')
                                if header_end != -1:
                                    header = entry[1:header_end]
                                    content_part = entry[header_end + 3:]
                                    
                                    # Extrahuj autora (vše po časovém razítku)
                                    if ' ' in header:
                                        author = header.split(' ', 1)[1]
                                    else:
                                        author = header
                                        
                                    history.append({
                                        "author": author,
                                        "content": content_part,
                                        "timestamp": datetime.now().isoformat()
                                    })
                        except Exception as e:
                            print(f"Chyba při parsování historie: {e}")
                            continue
            
            # Omez historii na posledních 50 zpráv
            history = history[-50:]
            
            # Ulož do souboru
            with open(HISTORY_FILE, 'w', encoding='utf-8') as f: 
                json.dump(history, f, ensure_ascii=False, indent=2)
                
        except Exception as e: 
            print(f"Chyba při ukládání historie: {e}")

    def _update_status_banner(self, text: str, speak_this_message: bool = True):
        try:
            if hasattr(self, 'status_banner_label'): 
                self.status_banner_label.config(text=text)
        except Exception as e:
            print(f"Chyba při aktualizaci status banneru: {e}")

    def _update_bridge_status(self, text: str):
        try:
            if hasattr(self, 'bridge_status_label'): 
                self.bridge_status_label.config(text=text, foreground=ACCENT_COLOR)
        except Exception as e:
            print(f"Chyba při aktualizaci bridge statusu: {e}")

    def _save_current_file(self):
        try:
            if not self.current_file_path: 
                self._update_status_banner("❌ Není vybrán soubor k uložení.")
                return
                
            # Načti starý obsah pro diff
            try:
                with open(self.current_file_path, 'r', encoding='utf-8', errors='ignore') as f: 
                    old = f.read()
            except Exception: 
                old = ""
                
            # Ulož nový obsah
            new = self.file_text.get("1.0", "end-1c")
            with open(self.current_file_path, 'w', encoding='utf-8') as f: 
                f.write(new)
                
            self._update_status_banner(f"✅ Soubor {os.path.basename(self.current_file_path)} úspěšně uložen.")
            self.show_diff_view(self.current_file_path, old_text=old, new_text=new)
            
        except Exception as e: 
            self._update_status_banner(f"❌ Chyba při uložení souboru: {e}")
        
    def open_file_in_viewer(self, path):
        try:
            self._clear_diff_if_needed()
            self.current_file_path = os.path.abspath(path)
            
            # Skryj všechny widgety v content frame
            for widget in self.viewer_content_frame.winfo_children(): 
                widget.pack_forget()

            _, ext = os.path.splitext(path)
            if ext.lower() in ['.png', '.jpg', '.jpeg', '.gif', '.bmp']:
                # Zobraz obrázek
                self.image_label.pack(fill="both", expand=True)
                img = Image.open(path)
                
                # Změň velikost podle velikosti frame
                w, h = self.viewer_content_frame.winfo_width(), self.viewer_content_frame.winfo_height()
                if w > 1 and h > 1: 
                    img.thumbnail((w, h), Image.Resampling.LANCZOS)

                self.viewer_image_photo = ImageTk.PhotoImage(img)
                self.image_label.config(image=self.viewer_image_photo)
                self.current_file_label.config(text=f"🖼️ {os.path.basename(path)}")
            else:
                # Zobraz text
                self.linenumbers.pack(side="left", fill="y")
                self.file_text.pack(side="left", fill="both", expand=True)
                
                file_text_scrollbar = ttk.Scrollbar(self.viewer_content_frame, orient="vertical", command=self.file_text.yview)
                file_text_scrollbar.pack(side="right", fill="y")
                self.file_text.config(yscrollcommand=file_text_scrollbar.set)
                
                with open(path, 'r', encoding='utf-8', errors='ignore') as f: 
                    content = f.read()
                    
                # Omez velikost pro zobrazení
                if len(content) > 30000: 
                    content = content[:30000] + "\n\n... (Soubor byl pro zobrazení zkrácen)"
                    
                self.file_text.config(state="normal")
                self.file_text.delete("1.0", "end")
                self.file_text.insert("1.0", content)
                
                self.current_file_label.config(text=f"📄 {os.path.basename(path)}")
                self.linenumbers.redraw()
                
        except Exception as e: 
            self._update_status_banner(f"❌ Chyba při otevření souboru: {e}")
    
    def show_viewer_context_menu(self, event):
        try:
            menu = tk.Menu(self.root, tearoff=0, bg=PANEL_BG, fg=ACCENT_COLOR)
            
            if self.current_file_path:
                menu.add_command(label="📎 Kopírovat cestu k souboru", 
                               command=lambda: (self.root.clipboard_clear(), 
                                              self.root.clipboard_append(self.current_file_path), 
                                              self._update_status_banner("📋 Cesta zkopírována.")))
            menu.post(event.x_root, event.y_root)
        except Exception as e:
            print(f"Chyba context menu: {e}")

    def show_diff_view(self, path: str, old_text: str, new_text: str):
        try:
            # Skryj všechny widgety
            for widget in self.viewer_content_frame.winfo_children(): 
                widget.pack_forget()
                
            # Zobraz text editor s diff
            self.linenumbers.pack(side="left", fill="y")
            self.file_text.pack(side="left", fill="both", expand=True)
            
            self.file_text.config(state="normal")
            self.file_text.delete("1.0", "end")
            
            # Vytvoř diff
            sm = difflib.SequenceMatcher(None, old_text.splitlines(), new_text.splitlines())
            
            for tag, i1, i2, j1, j2 in sm.get_opcodes():
                if tag == "equal":
                    for line in new_text.splitlines()[j1:j2]: 
                        self.file_text.insert("end", f"  {line}\n")
                elif tag == "insert":
                    for line in new_text.splitlines()[j1:j2]: 
                        self.file_text.insert("end", "+ ", ("diff_prefix",))
                        self.file_text.insert("end", f"{line}\n", ("diff_added",))
                elif tag == "delete":
                    for line in old_text.splitlines()[i1:i2]: 
                        self.file_text.insert("end", "- ", ("diff_prefix",))
                        self.file_text.insert("end", f"{line}\n", ("diff_deleted",))
                elif tag == "replace":
                    for line in old_text.splitlines()[i1:i2]: 
                        self.file_text.insert("end", "- ", ("diff_prefix",))
                        self.file_text.insert("end", f"{line}\n", ("diff_deleted",))
                    for line in new_text.splitlines()[j1:j2]: 
                        self.file_text.insert("end", "+ ", ("diff_prefix",))
                        self.file_text.insert("end", f"{line}\n", ("diff_added",))
            
            self.current_file_path = os.path.abspath(path)
            self.current_file_label.config(text=f"📄 {os.path.basename(path)} (náhled změn)")
            self.viewer_diff_mode = True
            self.linenumbers.redraw()
            
            self._update_status_banner("✅ Zobrazen náhled změn.")
        except Exception as e: 
            self._update_status_banner(f"❌ Chyba při zobrazení diffu: {e}")

    def _clear_diff_if_needed(self):
        if self.viewer_diff_mode: 
            self.viewer_diff_mode = False

    def activate_agent_view(self, agent_id: str):
        try:
            self._update_status_banner(f"Posílám požadavek na aktivaci pro {agent_id}...")
            status_val = self.system_statuses.get(agent_id, {})
            url = status_val.get('url') if isinstance(status_val, dict) else None
            self.bridge_client.send_message(SimpleMessage(agent_id, {"url": url, "use_profile": True}, "outgoing", msg_type='launch_agent'))
        except Exception as e:
            self._update_status_banner(f"❌ Chyba při aktivaci agenta: {e}")
    
    def connect_or_launch_manager(self):
        try:
            self._update_status_banner("🔍 Hledám Relay Server...")
            
            if self.bridge_client.connect(): 
                self._update_status_banner("✅ Připojeno k Relay Serveru.")
            else:
                self._update_status_banner("⚠️ Relay Server neběží, spouštím...")
                script_dir = os.path.dirname(os.path.abspath(__file__))
                server_script = os.path.join(script_dir, "relay_server.py")
                
                if not os.path.exists(server_script): 
                    self._update_status_banner(f"❌ Soubor '{server_script}' nenalezen!")
                    return
                    
                subprocess.Popen([sys.executable, server_script], cwd=script_dir)
                self.root.after(3000, self.retry_connection)
        except Exception as e: 
            self._update_status_banner(f"❌ Chyba spuštění Relay Serveru: {e}")
            
    def retry_connection(self): 
        try:
            self._update_status_banner("🔄 Zkouším se znovu připojit...")
            if self.bridge_client.connect():
                self._update_status_banner("✅ Úspěšně připojeno.")
            else:
                self._update_status_banner("❌ Připojení selhalo.")
        except Exception as e:
            self._update_status_banner(f"❌ Chyba při opakovaném připojení: {e}")
    
    def launch_debug_relay(self, url=None):
        try:
            if self.system_statuses.get('manager', ('Offline','red'))[0] != 'Online':
                self._update_status_banner("⚠️ Relay Manager neběží. Spouštím ho automaticky...")
                self.connect_or_launch_manager()
                self.root.after(3000, lambda: self._send_launch_debug_command(url))
            else: 
                self._send_launch_debug_command(url)
        except Exception as e:
            self._update_status_banner(f"❌ Chyba při spouštění debug relay: {e}")
        
    def _send_launch_debug_command(self, url=None):
        try:
            if not url: 
                url = simpledialog.askstring("Spustit Test Mode Relay", "Zadejte cílovou URL:", 
                                           initialvalue=getattr(self, 'last_debug_url', ''))
            if url:
                self.last_debug_url = url
                self._update_status_banner(f"🚀 Spouštím Test Mode pro URL: {url}...")
                self.bridge_client.send_message(SimpleMessage('TestAgent', {"url": url, "agent_id": "TestAgent"}, "outgoing", msg_type='launch_agent'))
        except Exception as e:
            self._update_status_banner(f"❌ Chyba při odesílání debug příkazu: {e}")

    def save_debug_profile(self, profile_name=None):
        try:
            if not self.system_statuses.get('TestAgent', ('Offline', 'red'))[0] == 'Online': 
                messagebox.showwarning("Upozornění", "❌ Nelze uložit profil, žádný Testovací Agent neběží.")
                return
                
            if not profile_name: 
                profile_name = simpledialog.askstring("Uložit profil", "Zadejte název profilu (např. A1):")
            if not profile_name: 
                return
                
            agent_name = simpledialog.askstring("Uložit profil", "Zadejte jméno agenta:", initialvalue=profile_name)
            if not agent_name: 
                return
                
            url = simpledialog.askstring("Uložit profil", "Potvrďte URL agenta:", 
                                       initialvalue=getattr(self, 'last_debug_url', ''))
            if not url: 
                return
                
            profile_path = os.path.join('relay', f"{profile_name}.json")
            
            if os.path.exists(profile_path) and not messagebox.askyesno("Přepsat profil", f"Profil '{profile_name}' již existuje. Chcete jej přepsat?"): 
                return
                
            profile_data = { 
                "agentName": agent_name, 
                "url": url, 
                "config": getattr(self, 'current_debug_config', {}) 
            }
            
            self.api.write_file(path=profile_path, content=json.dumps(profile_data, indent=2))
            self._update_status_banner(f"✅ Profil '{profile_name}' byl úspěšně uložen.")
        except Exception as e:
            self._update_status_banner(f"❌ Chyba při ukládání profilu: {e}")
    
    def toggle_debugging_mode(self):
        try:
            is_debugging = not getattr(self, 'is_debugging', False)
            self.is_debugging = is_debugging
            
            self.debug_button.config(text="⏹️ Zastavit Ladění" if is_debugging else "🛠️ Spustit Ladění")
            
            if is_debugging: 
                self.start_debugging()
            else: 
                self.stop_debugging()
        except Exception as e:
            self._update_status_banner(f"❌ Chyba při přepínání ladění: {e}")

    def start_debugging(self, mode='Message IN'):
        try:
            self._update_status_banner(f"🛠️ Zahajuji ladění pro '{mode}'...")
            
            default_config = { 
                "receiveParams": {"enabled": False, "messageContainerSelector": "CHANGE_ME"}, 
                "sendParams": {"enabled": False, "inputFieldSelector": "CHANGE_ME"} 
            }
            self.api.write_file(path='debug_default_params.json', content=json.dumps(default_config, indent=2))
            
            prompt = f"Zahájil jsem ladicí mód pro '{mode}' na URL: {getattr(self, 'last_debug_url', '')}. Tvým úkolem je analyzovat komunikaci a upravovat 'debug_default_params.json'."
            self._display("System", prompt, self.api_view, "system_message")
            
            threading.Thread(target=self._generate_gemini_response, args=(prompt, False), daemon=True).start()
        except Exception as e:
            self._update_status_banner(f"❌ Chyba při zahájení ladění: {e}")

    def stop_debugging(self): 
        try:
            self._update_status_banner("⏹️ Ladicí mód byl ukončen.")
        except Exception as e:
            self._update_status_banner(f"❌ Chyba při ukončení ladění: {e}")

    def report_agent_status_to_gemini(self):
        try:
            status_report = {key: val.cget('text') for key, val in self.status_indicators.items()}
            prompt = f"Aktuální stav systému:\n{json.dumps(status_report, indent=2)}"
            self._display("System", prompt, self.api_view, "system_message")
            threading.Thread(target=self._generate_gemini_response, args=(prompt, False), daemon=True).start()
        except Exception as e:
            self._update_status_banner(f"❌ Chyba při reportování statusu: {e}")
        
    def show_screenshot_menu(self):
        try:
            menu = tk.Menu(self.root, tearoff=0, bg=PANEL_BG, fg=ACCENT_COLOR)
            menu.add_command(label="📱 Celá obrazovka", command=lambda: self.take_screenshot('fullscreen'))
            menu.add_command(label="🖼️ Okno aplikace", command=lambda: self.take_screenshot('app_window'))
            menu.post(self.root.winfo_pointerx(), self.root.winfo_pointery())
        except Exception as e:
            self._update_status_banner(f"❌ Chyba při zobrazení menu: {e}")

    def take_screenshot(self, mode='fullscreen'):
        try:
            if mss is None: 
                self._update_status_banner("❌ Knihovna 'mss' není nainstalována.")
                return
                
            screenshots_dir = 'screenshots'
            os.makedirs(screenshots_dir, exist_ok=True)
            
            filename = f"screenshot_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.png"
            path = os.path.join(screenshots_dir, filename)
            
            with mss.mss() as sct:
                if mode == 'app_window':
                    monitor = {
                        "top": self.root.winfo_y(), 
                        "left": self.root.winfo_x(), 
                        "width": self.root.winfo_width(), 
                        "height": self.root.winfo_height()
                    }
                else:
                    monitor = sct.monitors[1]
                    
                sct_img = sct.grab(monitor)
                mss.tools.to_png(sct_img.rgb, sct_img.size, output=path)
            
            self._update_status_banner(f"📸 Screenshot uložen do '{path}'")
            self.open_file_in_viewer(path)
        except Exception as e:
            self._update_status_banner(f"❌ Chyba při vytváření screenshotu: {e}")
            
    def toggle_live_mode(self):
        try:
            self.live_mode_enabled.set(not self.live_mode_enabled.get())
            self._save_settings()
        except Exception as e:
            self._update_status_banner(f"❌ Chyba při přepínání live módu: {e}")

    def _update_live_mode_button_style(self):
        try:
            if hasattr(self, 'live_mode_button'):
                is_live = self.live_mode_enabled.get()
                self.live_mode_button.config(
                    text="⏹️ Vypnout Live Režim" if is_live else "▶️ Zapnout Live Režim", 
                    style="Live.TButton" if is_live else "TButton"
                )
        except Exception as e:
            print(f"Chyba při aktualizaci live button: {e}")

def main():
    """Hlavní funkce s error handlingem"""
    try:
        root = tk.Tk()
        app = AiCodeBoxApp(root)
        root.mainloop()
    except Exception as e:
        print(f"Kritická chyba aplikace: {e}")
        import traceback
        traceback.print_exc()
        
        # Pokus o zobrazení chyby uživateli
        try:
            import tkinter.messagebox as msgbox
            msgbox.showerror("Kritická chyba", f"Aplikace se nemohla spustit:\n\n{e}")
        except:
            pass

if __name__ == "__main__":
    main()
            