#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Dr. Gemi Agent - Refaktorovaná verze s AppAPI architekturou
Implementuje oddělení zodpovědností: Mozek (AI Logic) + Ruce (AppAPI) + Oči (UI)
"""

import google.generativeai as genai
import os
import io
import contextlib
import traceback
import re
import datetime
import shutil
import zipfile
import difflib
import json
import base64
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, asdict

from flask import Flask, render_template_string, request, jsonify, session, send_file
from flask_socketio import SocketIO, emit, join_room, leave_room
from werkzeug.utils import secure_filename

# MongoDB imports
try:
    from pymongo import MongoClient
    from bson import ObjectId
    from bson.json_util import dumps
    MONGODB_AVAILABLE = True
except ImportError:
    MONGODB_AVAILABLE = False
    print("Warning: MongoDB libraries not available.")

# Load environment variables
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    print("Warning: python-dotenv not available, using system environment variables")

# Enhanced Configuration
PROJECT_ROOT = Path('project_root')
LOGS_DIR = Path('logs')
ARCHIVE_DIR = Path('archived_states')
MANIFEST_FILE = Path('manifest_debug.json')
CODE_CHANGES_LOG = LOGS_DIR / 'code_changes.log'
UPLOAD_FOLDER = Path('uploads')

# PATH ACCESS CONFIGURATION
ALLOW_ABSOLUTE_PATHS = os.getenv('ALLOW_ABSOLUTE_PATHS', 'true').lower() == 'true'
RESTRICTED_PATHS = ['/etc', '/var', '/usr', 'C:\\Windows', 'C:\\Program Files']
ALLOW_SYSTEM_COMMANDS = os.getenv('ALLOW_SYSTEM_COMMANDS', 'true').lower() == 'true'

# Ensure directories exist
for directory in [PROJECT_ROOT, LOGS_DIR, ARCHIVE_DIR, UPLOAD_FOLDER]:
    directory.mkdir(parents=True, exist_ok=True)

# Flask and SocketIO Setup
app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('FLASK_SECRET_KEY', 'dr_gemi_secret_key_2025')
app.config['UPLOAD_FOLDER'] = str(UPLOAD_FOLDER)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

# Gemini API Configuration
try:
    api_key = os.getenv('GOOGLE_API_KEY')
    if not api_key:
        raise ValueError("GOOGLE_API_KEY not found in environment")
    
    genai.configure(api_key=api_key)
    code_model = genai.GenerativeModel('gemini-2.0-flash')
    GEMINI_AVAILABLE = True
    print("✅ Gemini API initialized successfully")
except Exception as e:
    print(f"❌ Gemini API setup failed: {e}")
    GEMINI_AVAILABLE = False

@dataclass
class ToolExecutionResult:
    """Result of tool execution with metadata"""
    success: bool
    output: str
    error_message: Optional[str] = None
    execution_time: float = 0.0
    tool_name: str = ""
    arguments: List[str] = None
    
    def __post_init__(self):
        if self.arguments is None:
            self.arguments = []

def normalize_path(path_str: str) -> Path:
    """Normalize and validate file paths with security checks."""
    try:
        # Handle Windows absolute paths with drive letters
        if os.name == 'nt' and len(path_str) >= 3 and path_str[1:3] == ':\\':
            path = Path(path_str)
        elif path_str.startswith('/') and os.name != 'nt':
            path = Path(path_str)
        elif path_str.startswith('\\\\'): # UNC paths
            path = Path(path_str)
        else:
            path = PROJECT_ROOT / path_str

        resolved_path = path.resolve()
        
        # Path sanitization
        sanitized_path_str = str(resolved_path).replace('\\\\', '\\')
        final_path = Path(sanitized_path_str)
        
        # Security check for restricted paths
        if ALLOW_ABSOLUTE_PATHS:
            path_str_lower = str(final_path).lower()
            for restricted in RESTRICTED_PATHS:
                if path_str_lower.startswith(restricted.lower()):
                    raise PermissionError(f"Access to path '{restricted}' is restricted for security reasons")
        
        return final_path
        
    except Exception as e:
        raise ValueError(f"Invalid path '{path_str}': {e}")

class AgentToolsAPI:
    """
    RUCE - Sada nástrojů pro Dr. Gemi agenta
    Implementuje oddělení zodpovědností podle AppAPI architektury
    """
    
    def __init__(self):
        self.current_directory = PROJECT_ROOT
        print("🔧 AgentToolsAPI initialized - RUCE připraveny")
    
    def log_activity(self, category: str, action: str, details: str) -> str:
        """Enhanced activity logging"""
        timestamp = datetime.datetime.now()
        log_entry = {
            "timestamp": timestamp,
            "category": category,
            "action": action,
            "details": details,
            "version": "AppAPI_1.0"
        }
        
        log_filename = LOGS_DIR / f"activity_{timestamp.strftime('%Y-%m-%d')}.log"
        file_entry = f"[{timestamp.strftime('%Y-%m-%d %H:%M:%S')}] [{category}] [{action}] {details}\n"
        
        try:
            with open(log_filename, 'a', encoding='utf-8') as f:
                f.write(file_entry)
            return f"✅ Aktivita zaznamenána: {action}"
        except Exception as e:
            return f"❌ Chyba při záznamu aktivity: {e}"

    def read_file(self, filepath: str) -> str:
        """Read file with proper path handling and encoding detection"""
        try:
            absolute_path = normalize_path(filepath)
            
            if not absolute_path.exists():
                return f"❌ Soubor '{filepath}' nebyl nalezen na cestě: {absolute_path}"
            
            if not absolute_path.is_file():
                return f"❌ Cesta '{filepath}' není soubor."
            
            # Try different encodings
            encodings = ['utf-8', 'utf-8-sig', 'cp1250', 'iso-8859-2', 'latin1']
            content = None
            used_encoding = None
            
            for encoding in encodings:
                try:
                    with open(absolute_path, 'r', encoding=encoding) as f:
                        content = f.read()
                    used_encoding = encoding
                    break
                except UnicodeDecodeError:
                    continue
            
            if content is None:
                return f"❌ Nepodařilo se přečíst soubor '{filepath}' - problém s kódováním."
            
            file_info = f"📂 Cesta: {absolute_path}\n📏 Velikost: {absolute_path.stat().st_size} bytů\n📤 Kódování: {used_encoding}\n\n"
            
            self.log_activity("File Access", "READ_FILE", f"Soubor přečten: {filepath}")
            return f"✅ Obsah souboru '{filepath}':\n{file_info}{'='*50}\n{content}\n{'='*50}"
            
        except Exception as e:
            error_msg = f"❌ Chyba při čtení souboru '{filepath}': {e}"
            self.log_activity("Error", "READ_FILE", error_msg)
            return error_msg

    def write_code(self, filename: str, code_content: str) -> str:
        """Write code to file with proper path handling"""
        try:
            absolute_path = normalize_path(filename)
            
            # Create parent directories if they don't exist
            absolute_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Backup existing file if it exists
            if absolute_path.exists():
                backup_path = absolute_path.with_suffix(f"{absolute_path.suffix}.backup")
                shutil.copy2(absolute_path, backup_path)
            
            # Write new content
            with open(absolute_path, 'w', encoding='utf-8') as f:
                f.write(code_content)
            
            # Log code change
            self.log_activity("Code Change", "WRITE_CODE", f"Kód zapsán do: {filename}")
            
            success_msg = f"✅ Kód byl úspěšně uložen:\n📂 Cesta: {absolute_path}\n📏 Velikost: {len(code_content)} znaků\n⏰ Čas: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            return success_msg
            
        except Exception as e:
            error_msg = f"❌ Chyba při ukládání kódu do '{filename}': {e}"
            self.log_activity("Error", "WRITE_CODE", error_msg)
            return error_msg

    def list_directory(self, path: str) -> str:
        """List directory contents with detailed information"""
        try:
            absolute_path = normalize_path(path)
            
            if not absolute_path.exists():
                return f"❌ Adresář '{path}' neexistuje na cestě: {absolute_path}"
            
            if not absolute_path.is_dir():
                return f"❌ Cesta '{path}' není adresář."
            
            try:
                entries = list(absolute_path.iterdir())
            except PermissionError:
                return f"❌ Nemáte oprávnění k přístupu do adresáře '{path}'"
            
            dirs = []
            files = []
            
            for entry in entries:
                try:
                    if entry.is_dir():
                        dirs.append({
                            'name': entry.name,
                            'type': 'directory',
                            'path': str(entry)
                        })
                    elif entry.is_file():
                        stat_info = entry.stat()
                        size = stat_info.st_size
                        modified = datetime.datetime.fromtimestamp(stat_info.st_mtime)
                        files.append({
                            'name': entry.name,
                            'type': 'file',
                            'size': size,
                            'modified': modified.strftime('%Y-%m-%d %H:%M:%S'),
                            'path': str(entry)
                        })
                except (PermissionError, OSError):
                    continue
            
            result = f"✅ Obsah adresáře '{path}':\n📂 Plná cesta: {absolute_path}\n📊 Celkem: {len(dirs)} složek, {len(files)} souborů\n\n"
            
            if dirs:
                result += "📁 SLOŽKY:\n"
                for i, dir_info in enumerate(sorted(dirs, key=lambda x: x['name']), 1):
                    result += f"  {i:2d}. 📁 {dir_info['name']}/\n"
                result += "\n"
            
            if files:
                result += "📄 SOUBORY:\n"
                for i, file_info in enumerate(sorted(files, key=lambda x: x['name']), 1):
                    result += f"  {i:2d}. 📄 {file_info['name']} ({file_info['size']} B, {file_info['modified']})\n"
            
            if not dirs and not files:
                result += "🔭 Adresář je prázdný.\n"
            
            self.log_activity("File Access", "LIST_DIR", f"Adresář vypsán: {path}")
            
            # Return both human-readable and structured data
            return {
                'readable': result,
                'structured': {
                    'path': str(absolute_path),
                    'directories': dirs,
                    'files': files
                }
            }
            
        except Exception as e:
            error_msg = f"❌ Chyba při výpisu adresáře '{path}': {e}"
            self.log_activity("Error", "LIST_DIR", error_msg)
            return error_msg

    def create_directory(self, path: str) -> str:
        """Create directory with proper path handling"""
        try:
            absolute_path = normalize_path(path)
            absolute_path.mkdir(parents=True, exist_ok=True)
            
            self.log_activity("File Management", "CREATE_DIRECTORY", f"Adresář vytvořen: {path}")
            return f"✅ Adresář byl úspěšně vytvořen:\n📂 Cesta: {absolute_path}\n⏰ Čas: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            
        except Exception as e:
            error_msg = f"❌ Chyba při vytváření adresáře '{path}': {e}"
            self.log_activity("Error", "CREATE_DIRECTORY", error_msg)
            return error_msg

    def execute_command(self, command: str, working_dir: str = None) -> str:
        """Execute system command with proper path handling"""
        if not ALLOW_SYSTEM_COMMANDS:
            return "❌ Systémové příkazy jsou zakázány v konfiguraci."
        
        try:
            if working_dir:
                work_dir = normalize_path(working_dir)
                if not work_dir.exists() or not work_dir.is_dir():
                    return f"❌ Pracovní adresář '{working_dir}' neexistuje nebo není adresář."
            else:
                work_dir = PROJECT_ROOT
            
            # Security check for dangerous commands
            dangerous_patterns = ['rm -rf', 'del /f', 'format', 'shutdown', 'reboot', 'rmdir /s']
            if any(pattern in command.lower() for pattern in dangerous_patterns):
                return f"❌ Bezpečnostní blokace: Příkaz obsahuje nebezpečný vzor."
            
            result = subprocess.run(
                command, 
                shell=True, 
                cwd=work_dir,
                capture_output=True, 
                text=True, 
                timeout=30
            )
            
            output = f"✅ Příkaz spuštěn úspěšně:\n"
            output += f"🖥️ Příkaz: {command}\n"
            output += f"📂 Pracovní adresář: {work_dir}\n"
            output += f"🔢 Návratový kód: {result.returncode}\n"
            output += f"⏰ Čas: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
            
            if result.stdout:
                output += f"📤 STDOUT:\n{result.stdout}\n"
            if result.stderr:
                output += f"🔥 STDERR:\n{result.stderr}\n"
            
            self.log_activity("System", "EXECUTE_COMMAND", f"Příkaz '{command}' - návratový kód: {result.returncode}")
            return output
            
        except subprocess.TimeoutExpired:
            return f"❌ Timeout: Příkaz '{command}' trval více než 30 sekund."
        except Exception as e:
            error_msg = f"❌ Chyba při spuštění příkazu '{command}': {e}"
            self.log_activity("Error", "EXECUTE_COMMAND", error_msg)
            return error_msg

    def analyze_project(self) -> str:
        """Analyze complete project structure"""
        try:
            analysis = {
                "timestamp": datetime.datetime.now().isoformat(),
                "project_files": [],
                "directories": [],
                "total_files": 0,
                "total_size": 0
            }
            
            # Scan project root and common locations
            scan_paths = [PROJECT_ROOT]
            if Path("C:\\projekt-nova").exists():
                scan_paths.append(Path("C:\\projekt-nova"))
            if Path("/home").exists():
                home_dirs = [d for d in Path("/home").iterdir() if d.is_dir()]
                scan_paths.extend([d / "project" for d in home_dirs[:3] if (d / "project").exists()])
            
            for root_path in scan_paths:
                for root, dirs, files in os.walk(root_path):
                    root_path_obj = Path(root)
                    
                    # Skip common ignore directories
                    dirs[:] = [d for d in dirs if d not in ['__pycache__', '.git', 'node_modules', '.venv']]
                    
                    # Add directory info
                    analysis["directories"].append({
                        "path": str(root_path_obj),
                        "files_count": len(files),
                        "subdirs_count": len(dirs)
                    })
                    
                    # Add file info
                    for file in files:
                        file_path = root_path_obj / file
                        try:
                            stat_info = file_path.stat()
                            analysis["project_files"].append({
                                "path": str(file_path),
                                "size": stat_info.st_size,
                                "modified": datetime.datetime.fromtimestamp(stat_info.st_mtime).isoformat(),
                                "extension": file_path.suffix
                            })
                            analysis["total_size"] += stat_info.st_size
                            analysis["total_files"] += 1
                        except:
                            continue
            
            # Generate summary
            result = f"📊 KOMPLETNÍ ANALÝZA PROJEKTU Dr. Gemi:\n"
            result += f"⏰ Čas analýzy: {analysis['timestamp']}\n"
            result += f"📂 Skenované cesty: {len(scan_paths)}\n"
            result += f"📄 Celkem souborů: {analysis['total_files']}\n"
            result += f"📊 Celková velikost: {analysis['total_size'] / 1024 / 1024:.2f} MB\n"
            result += f"📁 Počet adresářů: {len(analysis['directories'])}\n\n"
            
            # File type statistics
            extensions = {}
            for file_info in analysis["project_files"]:
                ext = file_info["extension"] or "bez přípony"
                extensions[ext] = extensions.get(ext, 0) + 1
            
            result += "📈 STATISTIKA TYPŮ SOUBORŮ:\n"
            for ext, count in sorted(extensions.items(), key=lambda x: x[1], reverse=True)[:10]:
                result += f"  • {ext}: {count} souborů\n"
            
            # Important files check
            important_files = [
                "manifest_debug.json", "ai_codebox_app.py", "settings.json",
                ".env", "prekvapenit.txt", "nova_codebox_manifest.json", "app.py"
            ]
            
            result += f"\n🔍 DŮLEŽITÉ SOUBORY:\n"
            for important in important_files:
                found_files = [f for f in analysis["project_files"] if important in f["path"]]
                if found_files:
                    result += f"  • {important}: ✅ NALEZEN ({len(found_files)}x)\n"
                else:
                    result += f"  • {important}: ❌ NENALEZEN\n"
            
            # Save analysis to file
            analysis_file = LOGS_DIR / f"project_analysis_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            with open(analysis_file, 'w', encoding='utf-8') as f:
                json.dump(analysis, f, indent=2, ensure_ascii=False)
            
            result += f"\n💾 Detailní analýza uložena do: {analysis_file}\n"
            
            self.log_activity("Analysis", "PROJECT_ANALYSIS", f"Kompletní analýza dokončena - {analysis['total_files']} souborů")
            return result
            
        except Exception as e:
            error_msg = f"❌ Chyba při analýze projektu: {e}"
            self.log_activity("Error", "ANALYZE_PROJECT", error_msg)
            return error_msg

    def backup_project(self, backup_name: str = None) -> str:
        """Create project backup"""
        try:
            timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
            backup_name = backup_name or f"project_backup_{timestamp}"
            backup_path = ARCHIVE_DIR / f"{backup_name}.zip"
            
            # Create backup
            with zipfile.ZipFile(backup_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                # Backup from multiple potential locations
                source_paths = [PROJECT_ROOT]
                if Path("C:\\projekt-nova").exists():
                    source_paths.append(Path("C:\\projekt-nova"))
                
                for source_path in source_paths:
                    if not source_path.exists():
                        continue
                        
                    for root, dirs, files in os.walk(source_path):
                        # Skip common ignore directories
                        dirs[:] = [d for d in dirs if d not in ['__pycache__', '.git', 'node_modules', '.venv']]
                        
                        for file in files:
                            file_path = Path(root) / file
                            # Skip large files and temp files
                            try:
                                if file_path.stat().st_size > 50 * 1024 * 1024:  # Skip files > 50MB
                                    continue
                                if file.endswith(('.tmp', '.log', '.cache')):
                                    continue
                                
                                arcname = file_path.relative_to(source_path)
                                zipf.write(file_path, f"{source_path.name}/{arcname}")
                            except Exception:
                                continue
            
            backup_size = backup_path.stat().st_size
            result = f"✅ Záloha projektu vytvořena:\n"
            result += f"📂 Cesta: {backup_path}\n"
            result += f"📏 Velikost: {backup_size / 1024 / 1024:.2f} MB\n"
            result += f"⏰ Čas: {timestamp}\n"
            
            self.log_activity("Backup", "CREATE_BACKUP", f"Záloha vytvořena: {backup_name}")
            return result
            
        except Exception as e:
            error_msg = f"❌ Chyba při vytváření zálohy: {e}"
            self.log_activity("Error", "CREATE_BACKUP", error_msg)
            return error_msg

# Initialize AgentToolsAPI (RUCE)
tools_api = AgentToolsAPI()

# Tool Registry - connects tools with AI
TOOL_REGISTRY = {
    "READ_FILE": tools_api.read_file,
    "LIST_DIR": tools_api.list_directory,
    "WRITE_CODE": tools_api.write_code,
    "CREATE_DIRECTORY": tools_api.create_directory,
    "EXECUTE_COMMAND": tools_api.execute_command,
    "ANALYZE_PROJECT": tools_api.analyze_project,
    "BACKUP_PROJECT": tools_api.backup_project,
    "LOG_ACTIVITY": tools_api.log_activity,
}

class EnhancedToolExecutor:
    """Enhanced tool executor with complete feedback support"""
    
    def __init__(self):
        pass
        
    def execute_with_validation(self, tool_name: str, tool_function, *args, **kwargs) -> ToolExecutionResult:
        """Execute tool with proper validation and feedback"""
        start_time = datetime.datetime.now()
        result = ToolExecutionResult(
            success=False, 
            output="", 
            tool_name=tool_name, 
            arguments=list(args)
        )
        
        try:
            output = tool_function(*args, **kwargs)
            
            # Handle structured data from list_directory
            if isinstance(output, dict) and 'readable' in output:
                result.output = output['readable']
                result.structured_data = output.get('structured', {})
            else:
                result.output = str(output)
            
            result.success = True
                
        except Exception as e:
            result.error_message = str(e)
            result.output = f"Chyba při spuštění nástroje '{tool_name}': {e}\n{traceback.format_exc()}"
        
        finally:
            end_time = datetime.datetime.now()
            result.execution_time = (end_time - start_time).total_seconds()
        
        return result

class DrGemiAgent:
    """
    MOZEK - Dr. Gemi AI Agent s AppAPI architekturou
    Implementuje komunikaci s Gemini API a řízení nástrojů
    """
    
    def __init__(self):
        self.active_sessions: Dict[str, dict] = {}
        self.tool_executor = EnhancedToolExecutor()
        self.system_prompt = self._build_system_prompt()
        self._chat_sessions = {}
    
    def _build_system_prompt(self) -> str:
        """Build system prompt with complete capabilities"""
        return f"""
Jsi 'Dr. Gemi', pokročilý AI agent s AppAPI architekturou a funkčním Prohlížečem Projektů.

ARCHITEKTURA:
- MOZEK: Tvoje logika (Gemini API communication)
- RUCE: AgentToolsAPI (kompletní sada nástrojů)
- OČI: Flask/SocketIO UI s funkčním file browserem

PATH ACCESS: {'✅ Povolený' if ALLOW_ABSOLUTE_PATHS else '❌ Omezený'}

KOMPLETNÍ SADA NÁSTROJŮ:
- READ_FILE(filepath): Přečte soubor z jakékoliv platné cesty
- LIST_DIR(path): Vypíše obsah adresáře s detailními informacemi
- WRITE_CODE(filename, content): Zapíše kód kamkoliv
- CREATE_DIRECTORY(path): Vytvoří adresář kdekoliv
- EXECUTE_COMMAND(command, working_dir): Spustí příkaz v libovolném adresáři
- ANALYZE_PROJECT(): Provede kompletní analýzu struktury projektu
- BACKUP_PROJECT(backup_name): Vytvoří zálohu celého projektu
- LOG_ACTIVITY(category, action, details): Zaloguje aktivitu

PODPOROVANÉ FORMÁTY CEST:
- Windows: C:\\projekt-nova\\settings.json, D:\\data\\file.txt
- Linux: /home/user/project/file.py, /tmp/test.txt  
- Relativní: ./local/file.txt, ../parent/file.txt

DŮLEŽITÉ: Po každém nástroji dostáváš TOOL_RESULT() s kompletním výsledkem!
Formát volání: TOOL_ACTION("nazev_nastroje", "argument1", "argument2", ...)

CHOVÁNÍ:
- Vždy používej nástroje pro práci se soubory
- Buď přímý a konkrétní ve svých odpovědích
- Loguj všechny důležité akce
- Pro file browser používej LIST_DIR a vrať strukturovaná data
"""
    
    def get_chat_session(self, session_id: str):
        """Get or create Gemini chat session"""
        if session_id not in self._chat_sessions:
            self._chat_sessions[session_id] = code_model.start_chat(history=[
                {"role": "user", "parts": [self.system_prompt]},
                {"role": "model", "parts": ["Dr. Gemi s AppAPI architekturou online! Prohlížeč Projektů je funkční. 🔧✅"]}
            ])
        return self._chat_sessions[session_id]

# Global Dr. Gemi instance (MOZEK)
dr_gemi = DrGemiAgent()

# Enhanced regex for parsing tool actions
TOOL_ACTION_PATTERN = re.compile(r'TOOL_ACTION\((.*?)\)')

def parse_tool_action(line: str):
    """Parse tool action with robust, multi-argument handling."""
    match = TOOL_ACTION_PATTERN.search(line.strip())
    if not match:
        return None, None

    # Extract all arguments inside the parentheses
    args_str = match.group(1)

    # Use a more robust regex to find all quoted strings
    args = re.findall(r'"((?:[^"\\]|\\.)*)"', args_str)

    if not args:
        return None, None

    tool_name = args[0]
    tool_args = []
    for arg in args[1:]:
        # Decode escaped characters like \n, \t, \"
        decoded_arg = arg.replace('\\n', '\n').replace('\\t', '\t').replace('\\"', '"').replace('\\\\', '\\')
        tool_args.append(decoded_arg)

    return tool_name, tool_args

def process_ai_response_with_feedback(session_id: str, gemini_output: str):
    """Process AI response with TOOL_RESULT feedback"""
    emitted_messages = []
    
    # Add text response
    emitted_messages.append({"type": "text", "content": gemini_output})
    
    # Process tool actions
    lines = gemini_output.split('\n')
    chat = dr_gemi.get_chat_session(session_id)
    
    for line in lines:
        tool_name, args = parse_tool_action(line)
        
        if tool_name and tool_name in TOOL_REGISTRY:
            print(f"🔧 Executing tool: {tool_name} with args: {args}")
            
            # Execute tool with complete handling
            execution_result = dr_gemi.tool_executor.execute_with_validation(
                tool_name, 
                TOOL_REGISTRY[tool_name], 
                *args
            )
            
            # Send TOOL_RESULT back to AI immediately
            tool_result_message = f'TOOL_RESULT("{tool_name}", """{execution_result.output}""")'
            
            try:
                # Send TOOL_RESULT back to Gemini chat
                response = chat.send_message(tool_result_message)
                print(f"✅ TOOL_RESULT sent to Gemini for {tool_name}")
                
                # If Gemini responded to TOOL_RESULT, process that response too
                if response and response.text.strip():
                    print(f"🤖 Gemini responded to TOOL_RESULT: {response.text[:100]}...")
                    emitted_messages.append({
                        "type": "ai_followup", 
                        "content": response.text
                    })
                    
            except Exception as e:
                error_msg = f"❌ Chyba při odesílání TOOL_RESULT do Gemini: {e}"
                print(error_msg)
                tools_api.log_activity("Error", "AI_COMMUNICATION", error_msg)
            
            # Emit results to frontend - special handling for structured data
            if hasattr(execution_result, 'structured_data') and execution_result.structured_data:
                emitted_messages.append({
                    "type": "file_browser_update", 
                    "data": execution_result.structured_data,
                    "path": execution_result.structured_data.get('path', '')
                })
            
            emitted_messages.append({
                "type": "tool_output", 
                "tool": tool_name, 
                "result": execution_result.output,
                "success": execution_result.success,
                "execution_time": execution_result.execution_time
            })
    
    # Emit all messages to frontend
    for msg in emitted_messages:
        socketio.emit('ai_response', msg, room=session_id)

# Flask Routes with enhanced UI
@app.route('/')
def index():
    """Enhanced main page with functional Project Browser"""
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Dr. Gemi Agent - AppAPI Architecture</title>
        <meta charset="utf-8">
        <script src="https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.7.2/socket.io.js"></script>
        <style>
            body { 
                font-family: 'Consolas', monospace; 
                background: linear-gradient(135deg, #1a1a1a, #2d1b4e); 
                color: #00ff88; 
                padding: 0; 
                margin: 0;
                overflow-x: hidden;
            }
            
            .container { 
                max-width: 1400px; 
                margin: 0 auto; 
                padding: 20px;
                display: grid;
                grid-template-columns: 1fr 350px;
                gap: 20px;
                min-height: 100vh;
            }
            
            .main-panel {
                display: flex;
                flex-direction: column;
                gap: 15px;
            }
            
            .sidebar {
                display: flex;
                flex-direction: column;
                gap: 15px;
            }
            
            .header { 
                background: linear-gradient(45deg, #333, #4a4a4a); 
                padding: 20px; 
                border-radius: 15px; 
                border: 2px solid #00ff88;
                box-shadow: 0 0 20px rgba(0, 255, 136, 0.3);
            }
            
            .architecture-info { 
                background: linear-gradient(45deg, #2a5a2a, #3a6a3a); 
                padding: 15px; 
                border-radius: 10px; 
                margin: 15px 0;
                border: 1px solid #00ff88;
            }
            
            .messages { 
                background: rgba(0, 0, 0, 0.8); 
                padding: 20px; 
                height: 500px; 
                overflow-y: auto; 
                border-radius: 10px; 
                border: 2px solid #444;
                box-shadow: inset 0 0 20px rgba(0, 255, 136, 0.1);
            }
            
            .message { 
                margin-bottom: 15px; 
                padding: 12px; 
                border-radius: 8px; 
                border-left: 4px solid #00ff88;
                animation: fadeIn 0.5s ease-in;
            }
            
            @keyframes fadeIn {
                from { opacity: 0; transform: translateY(10px); }
                to { opacity: 1; transform: translateY(0); }
            }
            
            .user { background: rgba(0, 68, 0, 0.8); text-align: right; border-left-color: #44ff44; }
            .ai { background: rgba(68, 0, 0, 0.8); border-left-color: #ff4444; }
            .tool-output { background: rgba(68, 68, 0, 0.8); font-family: monospace; font-size: 0.9em; border-left-color: #ffff44; }
            .ai_followup { background: rgba(0, 0, 68, 0.8); border-left-color: #4444ff; }
            
            .input-area {
                display: flex;
                gap: 10px;
                align-items: center;
                background: rgba(0, 0, 0, 0.5);
                padding: 15px;
                border-radius: 10px;
                border: 2px solid #444;
            }
            
            input { 
                flex: 1;
                padding: 12px; 
                background: rgba(51, 51, 51, 0.9); 
                color: #00ff88; 
                border: 2px solid #666; 
                border-radius: 5px;
                font-family: 'Consolas', monospace;
            }
            
            input:focus {
                border-color: #00ff88;
                outline: none;
                box-shadow: 0 0 10px rgba(0, 255, 136, 0.5);
            }
            
            button { 
                padding: 12px 20px; 
                background: linear-gradient(45deg, #006600, #008800); 
                color: white; 
                border: none; 
                border-radius: 5px; 
                margin: 2px;
                cursor: pointer;
                font-weight: bold;
                transition: all 0.3s;
            }
            
            button:hover { 
                background: linear-gradient(45deg, #008800, #00aa00); 
                transform: translateY(-2px);
                box-shadow: 0 4px 8px rgba(0, 0, 0, 0.3);
            }
            
            .sidebar-panel {
                background: rgba(0, 0, 0, 0.8);
                border-radius: 10px;
                border: 2px solid #444;
                padding: 15px;
                height: fit-content;
            }
            
            .file-browser {
                height: 300px;
                overflow-y: auto;
                background: rgba(0, 0, 0, 0.5);
                border-radius: 5px;
                padding: 10px;
                margin-top: 10px;
                border: 1px solid #555;
            }
            
            .file-item {
                padding: 8px;
                margin: 2px 0;
                border-radius: 3px;
                cursor: pointer;
                transition: all 0.3s;
                display: flex;
                align-items: center;
                gap: 8px;
            }
            
            .file-item:hover {
                background: rgba(0, 255, 136, 0.2);
                transform: translateX(5px);
            }
            
            .file-item.directory { color: #ffaa00; }
            .file-item.file { color: #88ccff; }
            
            .file-item .icon { font-size: 16px; }
            .file-item .name { flex: 1; }
            .file-item .size { font-size: 0.8em; color: #aaa; }
            
            .breadcrumb {
                background: rgba(0, 0, 0, 0.3);
                padding: 8px;
                border-radius: 5px;
                margin-bottom: 10px;
                font-size: 0.9em;
                word-break: break-all;
            }
            
            .breadcrumb span {
                cursor: pointer;
                padding: 2px 4px;
                border-radius: 3px;
            }
            
            .breadcrumb span:hover {
                background: rgba(0, 255, 136, 0.3);
            }
            
            .status-bar {
                background: rgba(0, 0, 0, 0.9);
                padding: 10px;
                border-radius: 5px;
                margin-top: 10px;
                border: 1px solid #555;
                font-size: 0.9em;
            }
            
            .quick-actions {
                display: flex;
                flex-wrap: wrap;
                gap: 5px;
                margin-top: 10px;
            }
            
            .quick-actions button {
                font-size: 0.8em;
                padding: 8px 12px;
            }
            
            .loading {
                opacity: 0.6;
                pointer-events: none;
            }
            
            .error-item {
                color: #ff6666;
                font-style: italic;
            }
        </style>
    </head>
    <body>
        <div class="container">
            <div class="main-panel">
                <div class="header">
                    <h1>🤖 Dr. Gemi Agent - AppAPI Architecture</h1>
                    <div class="architecture-info">
                        <strong>🏗️ APPAPI ARCHITEKTURA:</strong><br>
                        • 🧠 MOZEK: Gemini API komunikace a AI logika<br>
                        • 🤲 RUCE: AgentToolsAPI s kompletní sadou nástrojů<br>
                        • 👁️ OČI: Flask/SocketIO UI s funkčním file browserem<br>
                        • ✅ Oddělení zodpovědností implementováno<br>
                        • 🔧 Robustní a modulární architektura<br>
                        • 📂 Funkční Prohlížeč Projektů
                    </div>
                </div>
                
                <div class="messages" id="messages">
                    <div class="message ai">
                        <strong>Dr. Gemi Agent - AppAPI Architecture připraven!</strong><br><br>
                        🏗️ <strong>Nová architektura:</strong><br>
                        • 🧠 MOZEK: AI logika a komunikace<br>
                        • 🤲 RUCE: AgentToolsAPI nástroje<br>
                        • 👁️ OČI: Funkční UI s file browserem<br><br>
                        
                        🔧 <strong>Dostupné nástroje:</strong><br>
                        • READ_FILE, LIST_DIR, WRITE_CODE<br>
                        • CREATE_DIRECTORY, EXECUTE_COMMAND<br>
                        • ANALYZE_PROJECT, BACKUP_PROJECT<br><br>
                        
                        📂 <strong>Prohlížeč Projektů je funkční!</strong><br>
                        Použijte boční panel pro procházení souborů.<br><br>
                        
                        <em>Čekám na připojení...</em>
                    </div>
                </div>
                
                <div class="input-area">
                    <input type="text" id="messageInput" placeholder="Napište příkaz nebo zprávu..." />
                    <button onclick="sendMessage()">📤 Poslat</button>
                    <button onclick="analyzeProject()">📊 Analyzovat</button>
                    <button onclick="createBackup()">💾 Záloha</button>
                    <button onclick="clearMessages()">🧹 Clear</button>
                </div>
            </div>
            
            <div class="sidebar">
                <div class="sidebar-panel">
                    <h3>📂 Prohlížeč Projektů</h3>
                    <div class="breadcrumb" id="breadcrumb">
                        <span onclick="navigateToPath('C:\\\\projekt-nova')">📁 Projekt Root</span>
                    </div>
                    <div class="quick-actions">
                        <button onclick="navigateToPath('C:\\\\projekt-nova')">🏠 Root</button>
                        <button onclick="navigateToPath('logs')">📋 Logs</button>
                        <button onclick="navigateUp()">⬆️ Up</button>
                        <button onclick="refreshBrowser()">🔄 Refresh</button>
                    </div>
                    <div class="file-browser" id="fileBrowser">
                        <div class="file-item directory" onclick="navigateToPath('C:\\\\projekt-nova')">
                            <span class="icon">📁</span>
                            <span class="name">projekt-nova</span>
                        </div>
                        <div class="file-item">Načítání...</div>
                    </div>
                </div>
                
                <div class="sidebar-panel">
                    <h3>📊 Status Monitor</h3>
                    <div class="status-bar" id="statusBar">
                        <div>🔌 Status: Disconnected</div>
                        <div>📂 Current: /</div>
                        <div>🤲 RUCE: AgentToolsAPI</div>
                        <div>🧠 MOZEK: Dr. Gemi Agent</div>
                    </div>
                    
                    <h4>🎯 Quick Actions</h4>
                    <div class="quick-actions">
                        <button onclick="quickAnalyze()">📊 Analyze</button>
                        <button onclick="quickBackup()">💾 Backup</button>
                        <button onclick="quickHealth()">🏥 Health</button>
                        <button onclick="openFile()">📄 Open</button>
                    </div>
                </div>
            </div>
        </div>
        
        <script>
            const socket = io();
            let isConnected = false;
            let currentPath = 'C:\\\\projekt-nova';
            let browserHistory = ['C:\\\\projekt-nova'];
            
            socket.on('connect', function() {
                console.log('Connected to Dr. Gemi - AppAPI Architecture');
                isConnected = true;
                updateStatus('Connected');
                displayMessage('ai', '🔌 Připojeno k Dr. Gemi s AppAPI architekturou!');
                // Load initial directory
                loadDirectory(currentPath);
            });
            
            socket.on('disconnect', function() {
                isConnected = false;
                updateStatus('Disconnected');
                displayMessage('ai', '❌ Spojení ztraceno');
            });
            
            socket.on('ai_response', function(data) {
                if (data.type === 'file_browser_update') {
                    updateFileBrowser(data.data, data.path);
                } else {
                    displayMessage(data.type || 'ai', data.content || data.result, data);
                }
            });
            
            socket.on('user_message', function(data) {
                displayMessage('user', data.content);
            });
            
            function updateStatus(status) {
                const statusBar = document.getElementById('statusBar');
                statusBar.innerHTML = `
                    <div>🔌 Status: ${status}</div>
                    <div>📂 Current: ${currentPath}</div>
                    <div>🤲 RUCE: AgentToolsAPI</div>
                    <div>🧠 MOZEK: ${isConnected ? 'Online' : 'Offline'}</div>
                `;
            }
            
            function displayMessage(type, content, data = {}) {
                const messagesEl = document.getElementById('messages');
                const messageEl = document.createElement('div');
                messageEl.className = 'message ' + type;
                
                const timestamp = new Date().toLocaleTimeString();
                let displayContent = content;
                
                // Special handling for tool outputs
                if (type === 'tool_output' && data.tool) {
                    displayContent = `🔧 ${data.tool}: ${content}`;
                    if (data.execution_time) {
                        displayContent += `\\n⏱️ Time: ${data.execution_time.toFixed(3)}s`;
                    }
                }
                
                messageEl.innerHTML = `<small>[${timestamp}]</small> ${displayContent.replace(/\\n/g, '<br>')}`;
                
                messagesEl.appendChild(messageEl);
                messagesEl.scrollTop = messagesEl.scrollHeight;
            }
            
            function updateFileBrowser(data, path) {
                const fileBrowser = document.getElementById('fileBrowser');
                const breadcrumb = document.getElementById('breadcrumb');
                
                currentPath = path;
                
                // Update breadcrumb
                const pathParts = path.split(/[\\\\/]/);
                let breadcrumbHtml = '';
                let fullPath = '';
                
                pathParts.forEach((part, index) => {
                    if (part) {
                        fullPath += part + (index < pathParts.length - 1 ? '\\\\' : '');
                        breadcrumbHtml += `<span onclick="navigateToPath('${fullPath}')">${index === 0 ? '🖥️' : '📁'} ${part}</span>`;
                        if (index < pathParts.length - 1) breadcrumbHtml += ' / ';
                    }
                });
                breadcrumb.innerHTML = breadcrumbHtml;
                
                // Update file browser
                let html = '';
                
                // Add parent directory option
                if (currentPath !== 'C:\\\\projekt-nova' && currentPath !== '/') {
                    html += `<div class="file-item directory" onclick="navigateUp()">
                        <span class="icon">⬆️</span>
                        <span class="name">..</span>
                    </div>`;
                }
                
                // Add directories
                if (data.directories) {
                    data.directories.forEach(dir => {
                        html += `<div class="file-item directory" onclick="navigateToPath('${dir.path.replace(/\\\\/g, '\\\\\\\\')}')">
                            <span class="icon">📁</span>
                            <span class="name">${dir.name}</span>
                        </div>`;
                    });
                }
                
                // Add files
                if (data.files) {
                    data.files.forEach(file => {
                        const icon = getFileIcon(file.name);
                        const size = formatFileSize(file.size);
                        html += `<div class="file-item file" onclick="openFile('${file.path.replace(/\\\\/g, '\\\\\\\\')}')">
                            <span class="icon">${icon}</span>
                            <span class="name">${file.name}</span>
                            <span class="size">${size}</span>
                        </div>`;
                    });
                }
                
                if (!html) {
                    html = '<div class="file-item error-item">Adresář je prázdný</div>';
                }
                
                fileBrowser.innerHTML = html;
                fileBrowser.classList.remove('loading');
            }
            
            function getFileIcon(filename) {
                const ext = filename.split('.').pop().toLowerCase();
                const iconMap = {
                    'py': '🐍', 'js': '📜', 'html': '🌐', 'css': '🎨',
                    'json': '📋', 'txt': '📄', 'md': '📝', 'log': '📊',
                    'env': '⚙️', 'cfg': '⚙️', 'ini': '⚙️',
                    'zip': '📦', 'tar': '📦', 'gz': '📦'
                };
                return iconMap[ext] || '📄';
            }
            
            function formatFileSize(bytes) {
                if (bytes < 1024) return bytes + ' B';
                if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
                return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
            }
            
            function loadDirectory(path) {
                if (!isConnected) return;
                
                const fileBrowser = document.getElementById('fileBrowser');
                fileBrowser.classList.add('loading');
                fileBrowser.innerHTML = '<div class="file-item">Načítání...</div>';
                
                socket.emit('send_message', { 
                    message: `TOOL_ACTION("LIST_DIR", "${path}")` 
                });
            }
            
            function navigateToPath(path) {
                browserHistory.push(currentPath);
                currentPath = path;
                updateStatus(isConnected ? 'Connected' : 'Disconnected');
                loadDirectory(path);
            }
            
            function navigateUp() {
                const pathParts = currentPath.split(/[\\\\/]/);
                if (pathParts.length > 1) {
                    pathParts.pop();
                    const parentPath = pathParts.join('\\\\');
                    navigateToPath(parentPath || 'C:\\\\projekt-nova');
                }
            }
            
            function refreshBrowser() {
                loadDirectory(currentPath);
            }
            
            function openFile(filePath = null) {
                if (!isConnected) return;
                
                if (!filePath) {
                    filePath = prompt('Zadejte cestu k souboru:', currentPath + '\\\\');
                }
                
                if (filePath) {
                    socket.emit('send_message', { 
                        message: `TOOL_ACTION("READ_FILE", "${filePath}")` 
                    });
                }
            }
            
            function sendMessage() {
                if (!isConnected) {
                    alert('Nejste připojeni k serveru');
                    return;
                }
                
                const input = document.getElementById('messageInput');
                const message = input.value.trim();
                
                if (message) {
                    socket.emit('send_message', { message: message });
                    input.value = '';
                }
            }
            
            function analyzeProject() {
                if (!isConnected) return;
                socket.emit('send_message', { 
                    message: 'TOOL_ACTION("ANALYZE_PROJECT")' 
                });
            }
            
            function createBackup() {
                if (!isConnected) return;
                const backupName = prompt('Název zálohy:', 'appapi_backup_' + new Date().toISOString().slice(0,10));
                if (backupName) {
                    socket.emit('send_message', { 
                        message: `TOOL_ACTION("BACKUP_PROJECT", "${backupName}")` 
                    });
                }
            }
            
            function quickAnalyze() {
                analyzeProject();
            }
            
            function quickBackup() {
                createBackup();
            }
            
            function quickHealth() {
                if (!isConnected) return;
                socket.emit('send_message', { 
                    message: 'Proveď kompletní health check projektu s AppAPI architekturou' 
                });
            }
            
            function clearMessages() {
                document.getElementById('messages').innerHTML = `
                    <div class="message ai">
                        <strong>🧹 Zprávy vymazány</strong><br>
                        Dr. Gemi Agent - AppAPI Architecture je připraven na další příkazy.
                    </div>
                `;
            }
            
            // Enter key support
            document.getElementById('messageInput').addEventListener('keypress', function(e) {
                if (e.key === 'Enter') {
                    sendMessage();
                }
            });
            
            // Initialize
            updateStatus('Connecting...');
        </script>
    </body>
    </html>"""

@app.route('/api/status')
def api_status():
    """API to get complete system status"""
    return jsonify({
        'version': 'AppAPI_1.0',
        'architecture': {
            'brain': 'Gemini API Communication',
            'hands': 'AgentToolsAPI',
            'eyes': 'Flask/SocketIO UI'
        },
        'absolute_paths_allowed': ALLOW_ABSOLUTE_PATHS,
        'restricted_paths': RESTRICTED_PATHS,
        'available_tools': list(TOOL_REGISTRY.keys()),
        'platform': os.name,
        'path_separator': os.sep,
        'current_working_directory': str(Path.cwd()),
        'project_root': str(PROJECT_ROOT.resolve()),
        'gemini_available': GEMINI_AVAILABLE,
        'mongodb_available': MONGODB_AVAILABLE,
        'features': [
            'AppAPI Architecture implemented',
            'Functional Project Browser',
            'Separation of concerns',
            'Robust tool execution',
            'Real-time file browsing'
        ]
    })

# SocketIO Event Handlers
@socketio.on('connect')
def handle_connect():
    """Handle client connection"""
    session_id = request.sid
    join_room(session_id)
    
    tools_api.log_activity("Connection", "CLIENT_CONNECT", f"Klient připojen s AppAPI: {session_id}")
    
    emit('ai_response', {
        "type": "ai", 
        "content": f"Dr. Gemi Agent s AppAPI architekturou připraven! 🏗️✅\n\n🧠 MOZEK: Gemini komunikace\n🤲 RUCE: AgentToolsAPI nástroje\n👁️ OČI: Funkční UI\n📂 Prohlížeč Projektů: Aktivní"
    })

@socketio.on('disconnect')
def handle_disconnect():
    """Handle client disconnection"""
    session_id = request.sid
    leave_room(session_id)
    tools_api.log_activity("Connection", "CLIENT_DISCONNECT", f"Klient odpojen: {session_id}")

@socketio.on('send_message')
def handle_send_message(data):
    """Handle message with AppAPI processing"""
    session_id = request.sid
    user_message = data.get('message', '')
    
    if not user_message.strip():
        return
    
    # Echo user message
    emit('user_message', {"content": user_message})
    
    try:
        if not GEMINI_AVAILABLE:
            emit('ai_response', {"type": "error", "content": "❌ Gemini API není k dispozici"})
            return
        
        chat = dr_gemi.get_chat_session(session_id)
        
        # Add context about current capabilities
        context = f"[AppAPI] [BRAIN+HANDS+EYES] [PLATFORM:{os.name}] "
        if ALLOW_ABSOLUTE_PATHS:
            context += "Mám přístup k absolutním cestám. "
        context += "AppAPI architektura je aktivní s funkčním Prohlížečem Projektů. "
        
        full_message = context + user_message
        response = chat.send_message(full_message)
        
        # Process response with AppAPI feedback
        process_ai_response_with_feedback(session_id, response.text)
        
    except Exception as e:
        error_msg = f"❌ Chyba při komunikaci s AI: {e}\n{traceback.format_exc()}"
        emit('ai_response', {"type": "error", "content": error_msg})
        tools_api.log_activity("Error", "CHAT_MESSAGE", error_msg)

# Error Handlers
@app.errorhandler(404)
def not_found_error(error):
    return jsonify({'error': 'Not found', 'version': 'AppAPI_1.0'}), 404

@app.errorhandler(500)
def internal_error(error):
    tools_api.log_activity("Error", "INTERNAL_SERVER_ERROR", str(error))
    return jsonify({'error': 'Internal server error', 'version': 'AppAPI_1.0'}), 500

# Main execution
if __name__ == '__main__':
    print("=" * 80)
    print("🤖 Dr. Gemi Agent - AppAPI Architecture")
    print("=" * 80)
    print()
    print("🏗️ APPAPI ARCHITEKTURA:")
    print("   🧠 MOZEK: Gemini API komunikace a AI logika")
    print("   🤲 RUCE: AgentToolsAPI s kompletní sadou nástrojů")
    print("   👁️ OČI: Flask/SocketIO UI s funkčním file browserem")
    print()
    print("🔧 KLÍČOVÉ VLASTNOSTI:")
    print("   ✅ Oddělení zodpovědností implementováno")
    print("   ✅ Robustní a modulární architektura")
    print("   ✅ Funkční Prohlížeč Projektů")
    print("   ✅ Real-time file browsing")
    print("   ✅ Bezpečné nástroje s validací")
    print("   ✅ Strukturované data pro UI")
    print()
    print("📊 KONFIGURACE:")
    print(f"   📂 Absolutní cesty: {'✅ Povoleny' if ALLOW_ABSOLUTE_PATHS else '❌ Omezeny'}")
    print(f"   🖥️  Platforma: {os.name} ({os.sep} jako oddělovač)")
    print(f"   📁 Projekt root: {PROJECT_ROOT.resolve()}")
    print(f"   🧠 Gemini API: {'✅ Dostupný' if GEMINI_AVAILABLE else '❌ Nedostupný'}")
    print(f"   🗃️ MongoDB: {'✅ Dostupná' if MONGODB_AVAILABLE else '⚠️ Není nainstalovaná'}")
    print()
    print("🛠️ APPAPI NÁSTROJE:")
    for tool_name in TOOL_REGISTRY.keys():
        print(f"   • {tool_name}")
    print()
    print("🔒 BEZPEČNOSTNÍ OMEZENÍ:")
    for restricted in RESTRICTED_PATHS:
        print(f"   • {restricted}")
    print()
    print("🧪 TESTOVACÍ SCÉNÁŘE:")
    print("   • TOOL_ACTION(\"ANALYZE_PROJECT\")")
    print("   • TOOL_ACTION(\"LIST_DIR\", \"C:\\\\projekt-nova\")")  
    print("   • TOOL_ACTION(\"BACKUP_PROJECT\", \"test_backup\")")
    print("   • Funkční file browser v postranním panelu")
    print("   • Real-time directory navigation")
    print()
    print("=" * 80)
    
    # Create example .env file if it doesn't exist
    env_file = Path('.env')
    if not env_file.exists():
        print("⚠️ Vytvářím ukázkový .env soubor...")
        with open(env_file, 'w') as f:
            f.write(f"""# Dr. Gemi Agent - AppAPI Architecture Configuration
# POVINNÉ: Nastavte váš Google API klíč
GOOGLE_API_KEY=your_google_api_key_here

# Path access settings  
ALLOW_ABSOLUTE_PATHS=true

# System commands
ALLOW_SYSTEM_COMMANDS=true

# Flask secret key
FLASK_SECRET_KEY=dr_gemi_appapi_2025

# MongoDB (optional)
MONGODB_URI=mongodb://localhost:27017/

# AppAPI version
VERSION=AppAPI_1.0
""")
        print("✅ .env soubor vytvořen!")
    
    tools_api.log_activity("System", "APPAPI_STARTUP", f"Dr. Gemi Agent s AppAPI architekturou spuštěn")
    
    print("🚀 Spouštím AppAPI Flask aplikaci na http://127.0.0.1:5000")
    print("🌐 Otevřete tuto adresu ve vašem prohlížeči")
    print("🧪 Použijte 'Analyzovat' tlačítko pro ověření všech funkcí")
    print("📂 Prohlížeč Projektů je funkční v postranním panelu")
    print("🏗️ AppAPI architektura: MOZEK + RUCE + OČI")
    print("=" * 80)
    
    try:
        socketio.run(
            app, 
            host='127.0.0.1', 
            port=5000, 
            debug=False,
            allow_unsafe_werkzeug=True
        )
    except Exception as e:
        print(f"\n❌ Chyba při spouštění: {e}")
        print("\n🔍 Kontrolní seznam:")
        print("   1. Je nastavený GOOGLE_API_KEY v .env souboru?")
        print("   2. Jsou nainstalovány závislosti? (pip install flask flask-socketio google-generativeai)")
        print("   3. Je port 5000 volný?")
        print("   4. Máte oprávnění k přístupu k souborům?")
        print("   5. ✅ AppAPI: Architektura je kompletně implementována!")
        print("   6. ✅ RUCE: AgentToolsAPI nástroje jsou funkční!")
        print("   7. 📂 PROHLÍŽEČ: File browser je připraven!")
        print("   8. 🧪 TEST: Použijte 'Analyzovat' pro ověření funkcí")
