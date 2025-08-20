# -*- coding: utf-8 -*-
import sys
import time
import undetected_chromedriver as uc
import traceback
import json
import os
import asyncio
import threading

LOG_FILE_PATH = 'agent_console.log'
CONFIG_FILE_PATH = 'debug_default_params.json'

class Agent:
    def __init__(self, driver):
        self.driver = driver
        self.live_bridge_active = False

    def create_test_injection_script(self):
        # ... (kód beze změny)
        js_code = "..." 
        return js_code

    def create_observer_script(self, params):
        # ... (kód beze změny)
        js_code = "..."
        return js_code
    
    def watch_config_file(self):
        # ... (kód beze změny)
        ...

    def poll_for_messages(self):
        """Pokud je most aktivní, vyzvedává zprávy z fronty."""
        self.driver.execute_script("if (!window.ai_code_box_message_queue) { window.ai_code_box_message_queue = []; }")
        while True:
            if self.live_bridge_active:
                try:
                    message_text = self.driver.execute_script("return window.ai_code_box_message_queue.shift();")
                    if message_text:
                        response = {"type": "js_log", "content": message_text.strip()}
                        print(json.dumps(response)); sys.stdout.flush()
                except Exception: pass
            time.sleep(0.5)

    def listen_for_commands(self):
        """Naslouchá na stdin pro příkazy z Relay Manageru."""
        for line in sys.stdin:
            try:
                command = json.loads(line)
                action = command.get("action")
                if action == "inject_test_data":
                    self.driver.execute_script(self.create_test_injection_script())
                elif action == "activate_bridge":
                    self.live_bridge_active = True
                    print(json.dumps({"type": "status", "content": "Live bridge activated."})); sys.stdout.flush()

            except Exception as e:
                print(json.dumps({"type": "error", "content": f"Agent command failed: {e}"})); sys.stdout.flush()

def main(url):
    print("Spouštím finálního agenta...")
    driver = None
    log_file = open(LOG_FILE_PATH, 'w', encoding='utf-8')
    # Přesměrování stdout a stderr do souboru
    original_stdout = sys.stdout
    sys.stdout = sys.stderr = log_file

    try:
        driver = uc.Chrome()
        agent = Agent(driver)

        threading.Thread(target=agent.listen_for_commands, daemon=True).start()
        threading.Thread(target=agent.watch_config_file, daemon=True).start()
        threading.Thread(target=agent.poll_for_messages, daemon=True).start()

        driver.get(url)
        original_stdout.write(f"Stránka {url} je otevřená. Agent je připraven.\n")
        original_stdout.flush()
        
        while True: time.sleep(1)
    except Exception as e:
        traceback.print_exc(file=log_file)
    finally:
        sys.stdout = original_stdout # Vrátíme původní stdout
        input("\nStiskněte Enter pro ukončení...")
        if driver: driver.quit()
        log_file.close()

if __name__ == "__main__":
    if len(sys.argv) < 2: sys.exit(1)
    main(sys.argv[1])
