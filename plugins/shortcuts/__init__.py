import os
import subprocess
import json

class Plugin:
    def __init__(self, app_api):
        self.app_api = app_api
        self.config_path = os.path.join(os.path.dirname(__file__), 'config.json')
        self.load_config()

    def load_config(self):
        if os.path.exists(self.config_path):
            with open(self.config_path, 'r') as f:
                self.config = json.load(f)
        else:
            self.config = {
                "spotify_url": "https://open.spotify.com/", # Corrected URL
                "music_path": "/path/to/your/music",
                "applications": {
                    "calculator": "gnome-calculator",
                    "terminal": "gnome-terminal"
                }
            }
            self.save_config()

    def save_config(self):
        with open(self.config_path, 'w') as f:
            json.dump(self.config, f, indent=4)

    def handle_command(self, command_data):
        command_type = command_data.get("command")
        if command_type == "ping":
            self.app_api.speak("Pong!")
            return {"status": "success", "message": "Pong!"}
        elif command_type == "spotify_music":
            url = self.config.get("spotify_url")
            if url:
                self.app_api.launch_test_relay(url=url)
                self.app_api.speak("Spouštím Spotify.")
                return {"status": "success", "message": f"Opening Spotify: {url}"}
            else:
                self.app_api.speak("Spotify URL není nakonfigurována.")
                return {"status": "error", "message": "Spotify URL not configured."}
        elif command_type == "play_local_music":
            music_path = self.config.get("music_path")
            if music_path and os.path.exists(music_path):
                # Example: Use a simple media player (e.g., vlc, mpv)
                subprocess.Popen(["vlc", music_path])
                self.app_api.speak("Spouštím lokální hudbu.")
                return {"status": "success", "message": f"Playing local music from: {music_path}"}
            else:
                self.app_api.speak("Cesta k lokální hudbě není nakonfigurována nebo neexistuje.")
                return {"status": "error", "message": "Local music path not configured or does not exist."}
        elif command_type == "open_application":
            app_name = command_data.get("app_name")
            app_command = self.config["applications"].get(app_name)
            if app_command:
                subprocess.Popen([app_command])
                self.app_api.speak(f"Spouštím {app_name}.")
                return {"status": "success", "message": f"Opening application: {app_name}"}
            else:
                self.app_api.speak(f"Aplikace {app_name} není nakonfigurována.")
                return {"status": "error", "message": f"Application {app_name} not configured."}
        return {"status": "error", "message": "Unknown command"}