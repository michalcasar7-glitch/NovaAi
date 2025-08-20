#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Enhanced Dr. Gemi Agent - FIXED PATH ACCESS VERSION
Oprava přístupu k absolutním cestám na Windows/Linux systémech
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
from pathlib import Path, PureWindowsPath, PurePosixPath
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, asdict

from flask import Flask, render_template_string, request, jsonify, session
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

# Enhanced Configuration with PATH FIXES
PROJECT_ROOT = Path('project_root')
LOGS_DIR = Path('logs')
ARCHIVE_DIR = Path('archived_states')
MANIFEST_FILE = Path('manifest_debug.json')
CODE_CHANGES_LOG = LOGS_DIR / 'code_changes.log'
UPLOAD_FOLDER = Path('uploads')

# PATH ACCESS CONFIGURATION
ALLOW_ABSOLUTE_PATHS = os.getenv('ALLOW_ABSOLUTE_PATHS', 'true').lower() == 'true'
RESTRICTED_PATHS = ['/etc', '/var', '/usr', 'C:\\Windows', 'C:\\Program Files']
TOOL_EXECUTION_MODE = os.getenv('TOOL_EXECUTION_MODE', 'REAL')
ALLOW_SYSTEM_COMMANDS = os.getenv('ALLOW_SYSTEM_COMMANDS', 'true').lower() == 'true'

# Ensure directories exist
for directory in [PROJECT_ROOT, LOGS_DIR, ARCHIVE_DIR, UPLOAD_FOLDER]:
    directory.mkdir(parents=True, exist_ok=True)

# Flask and SocketIO Setup
app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('FLASK_SECRET_KEY', 'dr_gemi_secret_key_2025')
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
    """
    Normalize and validate file paths - FIXED VERSION
    Supports both absolute and relative paths on Windows/Linux
    """
    try:
        # Handle Windows absolute paths with drive letters
        if os.name == 'nt' and len(path_str) >= 3 and path_str[1:3] == ':\\':
            # Windows absolute path like C:\...
            path = Path(path_str)
        elif path_str.startswith('/') and os.name != 'nt':
            # Unix absolute path
            path = Path(path_str)
        elif path_str.startswith('\\\\'):
            # Windows UNC path
            path = Path(path_str)
        else:
            # Relative path - resolve against project root
            path = PROJECT_ROOT / path_str
        
        # Resolve to absolute path
        path = path.resolve()
        
        # Security check for restricted paths
        if ALLOW_ABSOLUTE_PATHS:
            path_str_lower = str(path).lower()
            for restricted in RESTRICTED_PATHS:
                if path_str_lower.startswith(restricted.lower()):
                    raise PermissionError(f"Access to path '{restricted}' is restricted for security reasons")
        
        return path
        
    except Exception as e:
        raise ValueError(f"Invalid path '{path_str}': {e}")

def log_activity_tool(category: str, action: str, details: str) -> str:
    """Enhanced activity logging"""
    timestamp = datetime.datetime.now()
    log_entry = {
        "timestamp": timestamp,
        "category": category,
        "action": action,
        "details": details,
        "execution_mode": TOOL_EXECUTION_MODE,
        "path_access_version": "FIXED_PATHS_1.0"
    }
    
    log_filename = LOGS_DIR / f"activity_{timestamp.strftime('%Y-%m-%d')}.log"
    file_entry = f"[{timestamp.strftime('%Y-%m-%d %H:%M:%S')}] [{category}] [{action}] {details} [FIXED PATHS]\n"
    
    try:
        with open(log_filename, 'a', encoding='utf-8') as f:
            f.write(file_entry)
        return f"✅ Aktivita zaznamenána [FIXED PATHS]"
    except Exception as e:
        return f"❌ Chyba při záznamu aktivity: {e}"

def read_file_tool(filepath: str) -> str:
    """FIXED: Enhanced read file tool with proper path handling"""
    try:
        # Use the fixed path normalization
        absolute_path = normalize_path(filepath)
        
        # Check if file exists
        if not absolute_path.exists():
            return f"❌ Soubor '{filepath}' (resolved: {absolute_path}) nebyl nalezen."
        
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
        
        file_info = f"📁 Cesta: {absolute_path}\n📏 Velikost: {absolute_path.stat().st_size} bytů\n🔤 Kódování: {used_encoding}\n\n"
        
        log_activity_tool("File Access", "READ_FILE", f"Soubor přečten: {filepath} -> {absolute_path}")
        return f"✅ Obsah souboru '{filepath}':\n{file_info}{'='*50}\n{content}\n{'='*50}"
        
    except PermissionError as e:
        error_msg = f"❌ Nemáte oprávnění k přístupu k souboru '{filepath}': {e}"
        log_activity_tool("Error", "READ_FILE", error_msg)
        return error_msg
    except Exception as e:
        error_msg = f"❌ Chyba při čtení souboru '{filepath}': {e}"
        log_activity_tool("Error", "READ_FILE", error_msg)
        return error_msg

def write_code_to_file_tool(filename: str, code_content: str) -> str:
    """FIXED: Enhanced write code tool with proper path handling"""
    if TOOL_EXECUTION_MODE == "SIMULATION":
        return f"[SIMULATION] Kód by byl zapsán do souboru '{filename}' ({len(code_content)} znaků)."
    
    try:
        # Use the fixed path normalization
        absolute_path = normalize_path(filename)
        
        # Create parent directories if they don't exist
        absolute_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Read old content for diff if file exists
        old_content = ""
        if absolute_path.exists():
            try:
                with open(absolute_path, 'r', encoding='utf-8') as f:
                    old_content = f.read()
            except:
                old_content = "[Previous content could not be read]"
        
        # Write new content
        with open(absolute_path, 'w', encoding='utf-8') as f:
            f.write(code_content)
        
        # Log code change
        log_code_change(str(absolute_path), old_content, code_content)
        log_activity_tool("Code Change", "WRITE_CODE", f"Kód zapsán do: {filename} -> {absolute_path}")
        
        return f"✅ Kód byl SKUTEČNĚ uložen do souboru:\n📁 Cesta: {absolute_path}\n📏 Velikost: {len(code_content)} znaků\n⏰ Čas: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        
    except PermissionError as e:
        error_msg = f"❌ Nemáte oprávnění k zápisu do '{filename}': {e}"
        log_activity_tool("Error", "WRITE_CODE", error_msg)
        return error_msg
    except Exception as e:
        error_msg = f"❌ Chyba při ukládání kódu do '{filename}': {e}"
        log_activity_tool("Error", "WRITE_CODE", error_msg)
        return error_msg

def list_directory_tool(path: str) -> str:
    """FIXED: Enhanced directory listing with proper path handling"""
    try:
        # Use the fixed path normalization
        absolute_path = normalize_path(path)
        
        if not absolute_path.exists():
            return f"❌ Adresář '{path}' (resolved: {absolute_path}) neexistuje."
        
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
                    dirs.append(entry.name)
                elif entry.is_file():
                    stat_info = entry.stat()
                    size = stat_info.st_size
                    modified = datetime.datetime.fromtimestamp(stat_info.st_mtime)
                    files.append(f"{entry.name} ({size} B, {modified.strftime('%Y-%m-%d %H:%M:%S')})")
            except (PermissionError, OSError):
                # Skip files we can't access
                continue
        
        result = f"✅ Obsah adresáře '{path}':\n📁 Plná cesta: {absolute_path}\n📊 Celkem: {len(dirs)} složek, {len(files)} souborů\n\n"
        
        if dirs:
            result += "📁 SLOŽKY:\n"
            for i, dir_name in enumerate(sorted(dirs), 1):
                result += f"  {i:2d}. {dir_name}/\n"
            result += "\n"
        
        if files:
            result += "📄 SOUBORY:\n"
            for i, file_info in enumerate(sorted(files), 1):
                result += f"  {i:2d}. {file_info}\n"
        
        if not dirs and not files:
            result += "📭 Adresář je prázdný.\n"
        
        log_activity_tool("File Access", "LIST_DIR", f"Adresář vypsán: {path} -> {absolute_path}")
        return result
        
    except PermissionError as e:
        error_msg = f"❌ Nemáte oprávnění k přístupu do adresáře '{path}': {e}"
        log_activity_tool("Error", "LIST_DIR", error_msg)
        return error_msg
    except Exception as e:
        error_msg = f"❌ Chyba při výpisu adresáře '{path}': {e}"
        log_activity_tool("Error", "LIST_DIR", error_msg)
        return error_msg

def create_directory_tool(path: str) -> str:
    """FIXED: Create directory with proper path handling"""
    if TOOL_EXECUTION_MODE == "SIMULATION":
        return f"[SIMULATION] Adresář '{path}' by byl vytvořen."
    
    try:
        # Use the fixed path normalization
        absolute_path = normalize_path(path)
        
        # Create directory and all parent directories
        absolute_path.mkdir(parents=True, exist_ok=True)
        
        log_activity_tool("File Management", "CREATE_DIRECTORY", f"Adresář vytvořen: {path} -> {absolute_path}")
        return f"✅ Adresář byl úspěšně vytvořen:\n📁 Cesta: {absolute_path}\n⏰ Čas: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        
    except PermissionError as e:
        error_msg = f"❌ Nemáte oprávnění k vytvoření adresáře '{path}': {e}"
        log_activity_tool("Error", "CREATE_DIRECTORY", error_msg)
        return error_msg
    except Exception as e:
        error_msg = f"❌ Chyba při vytváření adresáře '{path}': {e}"
        log_activity_tool("Error", "CREATE_DIRECTORY", error_msg)
        return error_msg

def execute_command_tool(command: str, working_dir: str = None) -> str:
    """FIXED: Execute system command with proper path handling"""
    if not ALLOW_SYSTEM_COMMANDS:
        return "❌ Systémové příkazy jsou zakázány v konfiguraci."
    
    if TOOL_EXECUTION_MODE == "SIMULATION":
        return f"[SIMULATION] Příkaz '{command}' by byl spuštěn v adresáři: {working_dir or os.getcwd()}"
    
    try:
        # Handle working directory
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
        output += f"🖥️  Příkaz: {command}\n"
        output += f"📁 Pracovní adresář: {work_dir}\n"
        output += f"🔢 Návratový kód: {result.returncode}\n"
        output += f"⏰ Čas: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        
        if result.stdout:
            output += f"📤 STDOUT:\n{result.stdout}\n"
        if result.stderr:
            output += f"📥 STDERR:\n{result.stderr}\n"
        
        log_activity_tool("System", "EXECUTE_COMMAND", f"Příkaz '{command}' - návratový kód: {result.returncode}")
        return output
        
    except subprocess.TimeoutExpired:
        return f"❌ Timeout: Příkaz '{command}' trval více než 30 sekund."
    except Exception as e:
        error_msg = f"❌ Chyba při spuštění příkazu '{command}': {e}"
        log_activity_tool("Error", "EXECUTE_COMMAND", error_msg)
        return error_msg

def log_code_change(filename: str, old_content: str, new_content: str):
    """Enhanced code change logging"""
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    diff = list(difflib.unified_diff(
        old_content.splitlines(keepends=True),
        new_content.splitlines(keepends=True),
        fromfile=f'a/{filename}',
        tofile=f'b/{filename}',
        lineterm=''
    ))
    
    try:
        with open(CODE_CHANGES_LOG, 'a', encoding='utf-8') as f:
            f.write(f"\n--- FIXED PATHS Code Change: {filename} at {timestamp} ---\n")
            if diff:
                f.writelines(diff)
            else:
                f.write("Žádné podstatné změny (soubor vytvořen nebo obsah beze změny).\n")
            f.write("-------------------------------------------\n")
    except Exception as e:
        print(f"Warning: Could not log code change: {e}")

# FIXED Tool Registry with path support
FIXED_TOOL_REGISTRY = {
    "READ_FILE": read_file_tool,
    "LIST_DIR": list_directory_tool,
    "WRITE_CODE": write_code_to_file_tool,
    "LOG_ACTIVITY": log_activity_tool,
    "EXECUTE_COMMAND": execute_command_tool,
    "CREATE_DIRECTORY": create_directory_tool,
}

class EnhancedToolExecutor:
    """Enhanced tool executor with FIXED path handling"""
    
    def __init__(self, execution_mode: str = "REAL"):
        self.execution_mode = execution_mode
        
    def execute_with_validation(self, tool_name: str, tool_function, *args, **kwargs) -> ToolExecutionResult:
        """Execute tool with proper validation and FIXED path handling"""
        start_time = datetime.datetime.now()
        result = ToolExecutionResult(
            success=False, 
            output="", 
            tool_name=tool_name, 
            arguments=list(args)
        )
        
        try:
            if self.execution_mode == "SIMULATION":
                result.output = f"[SIMULATION] Nástroj '{tool_name}' by byl spuštěn s argumenty: {args}"
                result.success = True
            elif self.execution_mode == "SAFE":
                # Safe mode - only allow read operations
                safe_tools = ["READ_FILE", "LIST_DIR", "LOG_ACTIVITY"]
                if tool_name in safe_tools:
                    result.output = tool_function(*args, **kwargs)
                    result.success = True
                else:
                    result.output = f"[SAFE MODE] Nástroj '{tool_name}' není povolen v bezpečném režimu."
                    result.error_message = "Tool blocked by safe mode"
            else:  # REAL mode with FIXED paths
                result.output = tool_function(*args, **kwargs)
                result.success = True
                
        except Exception as e:
            result.error_message = str(e)
            result.output = f"Chyba při spuštění nástroje '{tool_name}': {e}\n{traceback.format_exc()}"
        
        finally:
            end_time = datetime.datetime.now()
            result.execution_time = (end_time - start_time).total_seconds()
        
        return result

class DrGemiAgent:
    """Dr. Gemi - AI Agent with FIXED path handling"""
    
    def __init__(self):
        self.active_sessions: Dict[str, dict] = {}
        self.tool_executor = EnhancedToolExecutor(TOOL_EXECUTION_MODE)
        self.system_prompt = self._build_system_prompt()
        self._chat_sessions = {}
    
    def _build_system_prompt(self) -> str:
        """Build system prompt with FIXED path capabilities"""
        return f"""
Jsi 'Dr. Gemi', pokročilý AI agent s REÁLNÝMI schopnostmi a OPRAVENÝM přístupem k souborovému systému.

KLÍČOVÉ OPRAVY v této verzi:
- ✅ FIXED: Správný přístup k absolutním cestám (C:\\, /home/, atd.)
- ✅ FIXED: Podpora Windows i Linux cest
- ✅ FIXED: Automatické normalizování cest
- ✅ FIXED: Bezpečnostní kontroly pro kritické adresáře

EXECUTION MODE: {TOOL_EXECUTION_MODE}
PATH ACCESS: {'✅ Povolený' if ALLOW_ABSOLUTE_PATHS else '❌ Omezený'}

ROZŠÍŘENÉ NÁSTROJE s FIXED PATH SUPPORT:
- READ_FILE(filepath): Přečte soubor z JAKÉKOLIV platné cesty
- LIST_DIR(path): Vypíše obsah JAKÉHOKOLIV adresáře  
- WRITE_CODE(filename, content): Zapíše kód KAMKOLIV
- CREATE_DIRECTORY(path): Vytvoří adresář KDEKOLIV
- EXECUTE_COMMAND(command, working_dir): Spustí příkaz v libovolném adresáři

PODPOROVANÉ FORMÁTY CEST:
- Windows: C:\\projekt-nova\\settings.json, D:\\data\\file.txt
- Linux: /home/user/project/file.py, /tmp/test.txt  
- Relativní: ./local/file.txt, ../parent/file.txt
- UNC: \\\\server\\share\\file.txt

DŮLEŽITÉ: Po každém nástroji dostáváš TOOL_RESULT() s kompletním výsledkem!

Formát volání: TOOL_ACTION("nazev_nastroje", "argument1", "argument2", ...)
"""
    
    def get_chat_session(self, session_id: str):
        """Get or create Gemini chat session"""
        if session_id not in self._chat_sessions:
            self._chat_sessions[session_id] = code_model.start_chat(history=[
                {"role": "user", "parts": [self.system_prompt]},
                {"role": "model", "parts": ["Dr. Gemi online s FIXED path access! Mohu nyní přistupovat k souborům kdekoliv na systému. 🔧✅"]}
            ])
        return self._chat_sessions[session_id]

# Global Dr. Gemi instance
dr_gemi = DrGemiAgent()

# Enhanced regex for parsing tool actions
TOOL_ACTION_PATTERN = re.compile(r'TOOL_ACTION\("([^"]+)"(?:,\s*"((?:[^"\\]|\\.)*)?")?(?:,\s*"((?:[^"\\]|\\.)*)?")?(?:,\s*"((?:[^"\\]|\\.)*)?")?(?:,\s*"((?:[^"\\]|\\.)*)?")?(?:,\s*"((?:[^"\\]|\\.)*)?")?(?:,\s*"((?:[^"\\]|\\.)*)?")?(?:,\s*"((?:[^"\\]|\\.)*)?")?(?:,\s*"((?:[^"\\]|\\.)*)?")?(?:,\s*"((?:[^"\\]|\\.)*)?")?(?:,\s*"((?:[^"\\]|\\.)*)?")?(?:,\s*"((?:[^"\\]|\\.)*)?")?(?:,\s*"((?:[^"\\]|\\.)*)?")?(?:,\s*"((?:[^"\\]|\\.)*)?")?(?:,\s*"((?:[^"\\]|\\.)*)?")?(?:,\s*"((?:[^"\\]|\\.)*)?")?(?:,\s*"((?:[^"\\]|\\.)*)?")?(?:,\s*"((?:[^"\\]|\\.)*)?")?(?:,\s*"((?:[^"\\]|\\.)*)?")?(?:,\s*"((?:[^"\\]|\\.)*)?")?\)')

def parse_tool_action(line: str):
    """Parse tool action with fixed argument handling"""
    match = TOOL_ACTION_PATTERN.search(line.strip())
    if match:
        tool_name = match.group(1)
        args = [arg for arg in match.groups()[1:] if arg is not None]
        
        # Decode escaped characters in arguments
        decoded_args = []
        for arg in args:
            if arg:
                decoded_arg = arg.replace('\\n', '\n').replace('\\t', '\t').replace('\\"', '"').replace('\\\\', '\\')
                decoded_args.append(decoded_arg)
        
        return tool_name, decoded_args
    return None, None

def process_ai_response_with_fixed_paths(session_id: str, gemini_output: str):
    """Process AI response with FIXED path handling"""
    emitted_messages = []
    
    # Add text response with path access indicator
    path_indicator = f"[FIXED PATHS] " if ALLOW_ABSOLUTE_PATHS else "[RESTRICTED PATHS] "
    mode_indicator = f"[{TOOL_EXECUTION_MODE}] "
    emitted_messages.append({"type": "text", "content": mode_indicator + path_indicator + gemini_output})
    
    # Process tool actions
    lines = gemini_output.split('\n')
    chat = dr_gemi.get_chat_session(session_id)
    
    for line in lines:
        tool_name, args = parse_tool_action(line)
        
        if tool_name and tool_name in FIXED_TOOL_REGISTRY:
            # Execute tool with FIXED path handling
            execution_result = dr_gemi.tool_executor.execute_with_validation(
                tool_name, 
                FIXED_TOOL_REGISTRY[tool_name], 
                *args
            )
            
            # Send complete result back to AI
            tool_result_message = f'TOOL_RESULT("{tool_name}", """{execution_result.output}""")'
            
            try:
                chat.send_message(tool_result_message)
                print(f"✅ FIXED PATHS: Sent tool result to Gemini: {tool_name}")
            except Exception as e:
                error_msg = f"Chyba při odesílání TOOL_RESULT do Gemini: {e}"
                log_activity_tool("Error", "AI_COMMUNICATION", error_msg)
            
            # Emit results to frontend
            emitted_messages.append({
                "type": "tool_output", 
                "tool": tool_name, 
                "result": execution_result.output,
                "success": execution_result.success,
                "execution_time": execution_result.execution_time
            })
            
            emitted_messages.append({
                "type": "tool_result",
                "tool": tool_name,
                "result": execution_result.output,
                "success": execution_result.success
            })
    
    # Emit all messages
    for msg in emitted_messages:
        socketio.emit('ai_response', msg, room=session_id)

# Flask Routes
@app.route('/')
def index():
    """Main page"""
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Dr. Gemi Agent - FIXED PATHS</title>
        <meta charset="utf-8">
        <script src="https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.7.2/socket.io.js"></script>
        <style>
            body { font-family: monospace; background: #1a1a1a; color: #00ff00; padding: 20px; }
            .container { max-width: 1200px; margin: 0 auto; }
            .header { background: #333; padding: 20px; border-radius: 10px; margin-bottom: 20px; }
            .fix-info { background: #2a5a2a; padding: 15px; border-radius: 5px; margin: 15px 0; }
            .messages { background: #222; padding: 20px; height: 400px; overflow-y: auto; border-radius: 5px; margin-bottom: 20px; }
            .message { margin-bottom: 10px; padding: 10px; border-radius: 5px; }
            .user { background: #004400; text-align: right; }
            .ai { background: #440000; }
            .tool-output { background: #444400; font-family: monospace; font-size: 0.9em; }
            input { width: 80%; padding: 10px; background: #333; color: #00ff00; border: 1px solid #666; }
            button { padding: 10px 20px; background: #006600; color: white; border: none; border-radius: 3px; margin: 5px; }
            button:hover { background: #008800; }
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>🤖 Dr. Gemi Agent - FIXED PATH ACCESS</h1>
                <div class="fix-info">
                    <strong>✅ KLÍČOVÉ OPRAVY:</strong><br>
                    • Správný přístup k absolutním cestám (C:\, /home/, atd.)<br>
                    • Podpora Windows i Linux formátů cest<br>
                    • Automatické normalizování a validace cest<br>
                    • Bezpečnostní kontroly pro systémové adresáře<br>
                    • Vylepšené chybové hlášky s detailními informacemi
                </div>
            </div>
            
            <div class="messages" id="messages">
                <div class="message ai">
                    <strong>Dr. Gemi Agent - FIXED PATHS je připraven!</strong><br><br>
                    🔧 <strong>Nové schopnosti:</strong><br>
                    • Přístup k C:\projekt-nova\settings.json ✅<br>
                    • Výpis složek z jakéhokoliv adresáře ✅<br>
                    • Vytváření souborů kdekoliv na systému ✅<br>
                    • Normalizace cest pro Windows/Linux ✅<br><br>
                    
                    <strong>Testovací příkazy:</strong><br>
                    • "LIST_DIR C:\projekt-nova"<br>
                    • "READ_FILE C:\projekt-nova\settings.json"<br>
                    • "WRITE_CODE C:\test\novy_soubor.txt content"<br><br>
                    
                    <em>Čekám na připojení...</em>
                </div>
            </div>
            
            <div>
                <input type="text" id="messageInput" placeholder="Napište příkaz nebo zprávu..." />
                <button onclick="sendMessage()">Poslat</button>
                <button onclick="testPaths()">Test Path Access</button>
                <button onclick="clearMessages()">Clear</button>
            </div>
        </div>
        
        <script>
            const socket = io();
            let isConnected = false;
            
            socket.on('connect', function() {
                console.log('Connected to Dr. Gemi - FIXED PATHS');
                isConnected = true;
                displayMessage('ai', '🔌 Připojeno k Dr. Gemi s FIXED PATH ACCESS!');
            });
            
            socket.on('disconnect', function() {
                isConnected = false;
                displayMessage('ai', '❌ Spojení ztraceno');
            });
            
            socket.on('ai_response', function(data) {
                displayMessage(data.type || 'ai', data.content || data.result);
            });
            
            socket.on('user_message', function(data) {
                displayMessage('user', data.content);
            });
            
            function displayMessage(type, content) {
                const messagesEl = document.getElementById('messages');
                const messageEl = document.createElement('div');
                messageEl.className = 'message ' + type;
                
                const timestamp = new Date().toLocaleTimeString();
                messageEl.innerHTML = `<small>[${timestamp}]</small> ${content}`;
                
                messagesEl.appendChild(messageEl);
                messagesEl.scrollTop = messagesEl.scrollHeight;
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
            
            function testPaths() {
                if (!isConnected) {
                    alert('Nejste připojeni k serveru');
                    return;
                }
                
                const testMessage = `Test FIXED PATH ACCESS:
1. TOOL_ACTION("LIST_DIR", "C:\\projekt-nova")
2. TOOL_ACTION("READ_FILE", "C:\\projekt-nova\\settings.json")  
3. TOOL_ACTION("CREATE_DIRECTORY", "C:\\temp\\test_dr_gemi")
4. TOOL_ACTION("WRITE_CODE", "C:\\temp\\test_dr_gemi\\test_file.txt", "Test FIXED paths!\\nDr. Gemi má nyní správný přístup k cestám.")

Očekávání: Všechny operace by měly fungovat s absolutními cestami!`;
                
                socket.emit('send_message', { message: testMessage });
            }
            
            function clearMessages() {
                document.getElementById('messages').innerHTML = `
                    <div class="message ai">
                        <strong>🧹 Zprávy vymazány</strong><br>
                        Dr. Gemi Agent - FIXED PATHS je připraven na další příkazy.
                    </div>
                `;
            }
            
            // Enter key support
            document.getElementById('messageInput').addEventListener('keypress', function(e) {
                if (e.key === 'Enter') {
                    sendMessage();
                }
            });
        </script>
    </body>
    </html>"""

@app.route('/api/path_status')
def api_path_status():
    """API to get path access status"""
    return jsonify({
        'absolute_paths_allowed': ALLOW_ABSOLUTE_PATHS,
        'restricted_paths': RESTRICTED_PATHS,
        'execution_mode': TOOL_EXECUTION_MODE,
        'available_tools': list(FIXED_TOOL_REGISTRY.keys()),
        'platform': os.name,
        'path_separator': os.sep,
        'current_working_directory': str(Path.cwd()),
        'project_root': str(PROJECT_ROOT.resolve()),
        'fixes': [
            'Správný přístup k absolutním cestám',
            'Podpora Windows i Linux cest', 
            'Automatické normalizování cest',
            'Bezpečnostní kontroly',
            'Vylepšené chybové hlášky'
        ]
    })

# SocketIO Event Handlers
@socketio.on('connect')
def handle_connect():
    """Handle client connection"""
    session_id = request.sid
    join_room(session_id)
    
    log_activity_tool("Connection", "CLIENT_CONNECT", f"Klient připojen s FIXED paths: {session_id}")
    
    # Send welcome message
    emit('ai_response', {
        "type": "ai", 
        "content": f"Dr. Gemi Agent s FIXED PATH ACCESS připraven! 🔧✅\n\nPlatforma: {os.name}\nAbsolutní cesty: {'✅ Povoleny' if ALLOW_ABSOLUTE_PATHS else '❌ Omezeny'}\nExecution mode: {TOOL_EXECUTION_MODE}"
    })

@socketio.on('disconnect')
def handle_disconnect():
    """Handle client disconnection"""
    session_id = request.sid
    leave_room(session_id)
    log_activity_tool("Connection", "CLIENT_DISCONNECT", f"Klient odpojen: {session_id}")

@socketio.on('send_message')
def handle_send_message(data):
    """Handle message with FIXED path processing"""
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
        
        # Add context about current path capabilities
        path_context = f"[FIXED_PATHS] [MODE:{TOOL_EXECUTION_MODE}] [PLATFORM:{os.name}] "
        if ALLOW_ABSOLUTE_PATHS:
            path_context += "Můžu přistupovat k absolutním cestám. "
        path_context += "Všechny nástroje mají OPRAVENOU podporu cest. "
        
        full_message = path_context + user_message
        response = chat.send_message(full_message)
        
        # Process response with FIXED paths
        process_ai_response_with_fixed_paths(session_id, response.text)
        
    except Exception as e:
        error_msg = f"❌ Chyba při komunikaci s AI: {e}\n{traceback.format_exc()}"
        emit('ai_response', {"type": "error", "content": error_msg})
        log_activity_tool("Error", "CHAT_MESSAGE", error_msg)

@socketio.on('test_path_access')
def handle_test_path_access():
    """Test FIXED path access capabilities"""
    session_id = request.sid
    
    test_commands = [
        'TOOL_ACTION("LIST_DIR", "C:\\")',
        'TOOL_ACTION("LIST_DIR", ".")', 
        'TOOL_ACTION("CREATE_DIRECTORY", "test_fixed_paths")',
        'TOOL_ACTION("WRITE_CODE", "test_fixed_paths/test.txt", "FIXED path test")',
        'TOOL_ACTION("READ_FILE", "test_fixed_paths/test.txt")'
    ]
    
    test_message = f"""KOMPLEXNÍ TEST FIXED PATH ACCESS:

{chr(10).join(test_commands)}

Očekávané výsledky:
✅ Všechny cesty by měly být správně zpracovány
✅ Absolutní i relativní cesty by měly fungovat  
✅ Automatické vytváření rodičovských adresářů
✅ Správné chybové hlášky při problémech"""
    
    handle_send_message({"message": test_message})

# Error Handlers
@app.errorhandler(404)
def not_found_error(error):
    return jsonify({'error': 'Not found', 'fix_version': 'FIXED_PATHS_1.0'}), 404

@app.errorhandler(500)
def internal_error(error):
    log_activity_tool("Error", "INTERNAL_SERVER_ERROR", str(error))
    return jsonify({'error': 'Internal server error', 'fix_version': 'FIXED_PATHS_1.0'}), 500

# Main execution
if __name__ == '__main__':
    print("=" * 80)
    print("🤖 Dr. Gemi Agent - FIXED PATH ACCESS VERSION")
    print("=" * 80)
    print()
    print("🔧 KLÍČOVÉ OPRAVY:")
    print("   ✅ Správný přístup k absolutním cestám")
    print("   ✅ Podpora Windows (C:\\) i Linux (/home/) cest")
    print("   ✅ Automatické normalizování a validace cest")
    print("   ✅ Bezpečnostní kontroly pro systémové adresáře")
    print("   ✅ Vylepšené chybové hlášky s detailními informacemi")
    print()
    print("📊 KONFIGURACE:")
    print(f"   🔧 Execution Mode: {TOOL_EXECUTION_MODE}")
    print(f"   🔐 Absolutní cesty: {'✅ Povoleny' if ALLOW_ABSOLUTE_PATHS else '❌ Omezeny'}")
    print(f"   🖥️  Platforma: {os.name} ({os.sep} jako oddělovač)")
    print(f"   📁 Projekt root: {PROJECT_ROOT.resolve()}")
    print(f"   🧠 Gemini API: {'✅ Dostupný' if GEMINI_AVAILABLE else '❌ Nedostupný'}")
    print()
    print("🛠️ DOSTUPNÉ NÁSTROJE (s FIXED path support):")
    for tool_name in FIXED_TOOL_REGISTRY.keys():
        print(f"   • {tool_name}")
    print()
    print("🔒 BEZPEČNOSTNÍ OMEZENÍ:")
    for restricted in RESTRICTED_PATHS:
        print(f"   • {restricted}")
    print()
    print("📝 TESTOVACÍ SCÉNÁŘE:")
    print("   • LIST_DIR C:\\projekt-nova")
    print("   • READ_FILE C:\\projekt-nova\\settings.json")  
    print("   • WRITE_CODE C:\\temp\\test.txt content")
    print("   • CREATE_DIRECTORY C:\\temp\\new_folder")
    print()
    print("=" * 80)
    
    # Create example .env file if it doesn't exist
    env_file = Path('.env')
    if not env_file.exists():
        print("⚠️  Vytvářím ukázkový .env soubor...")
        with open(env_file, 'w') as f:
            f.write(f"""# Dr. Gemi Agent - FIXED PATH ACCESS Configuration
# POVINNÉ: Nastavte váš Google API klíč
GOOGLE_API_KEY=your_google_api_key_here

# Path access settings  
ALLOW_ABSOLUTE_PATHS=true

# Execution mode (REAL, SIMULATION, SAFE)
TOOL_EXECUTION_MODE=REAL

# System commands
ALLOW_SYSTEM_COMMANDS=true

# Flask secret key
FLASK_SECRET_KEY=dr_gemi_fixed_paths_2025

# Fixed paths version
PATH_FIX_VERSION=FIXED_PATHS_1.0
""")
        print("✅ .env soubor vytvořen!")
    
    log_activity_tool("System", "FIXED_PATHS_STARTUP", f"Dr. Gemi Agent s FIXED PATH ACCESS spuštěn - Mode: {TOOL_EXECUTION_MODE}, Paths: {'Allowed' if ALLOW_ABSOLUTE_PATHS else 'Restricted'}")
    
    print("🚀 Spouštím FIXED Flask aplikaci na http://127.0.0.1:5000")
    print("🌐 Otevřete tuto adresu ve vašem prohlížeči")
    print("🧪 Použijte 'Test Path Access' tlačítko pro ověření oprav")
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
        print("   5. ✅ FIXED: Přístup k cestám je nyní opraven!")