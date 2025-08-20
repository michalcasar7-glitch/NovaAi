# http_server.py

from http.server import BaseHTTPRequestHandler, HTTPServer
import json

# Nastavení serveru
HOST = 'localhost'
PORT = 8888

# Toto je náš "zachytač" zpráv
class RequestHandler(BaseHTTPRequestHandler):
    
    def _send_cors_headers(self):
        """Odešle hlavičky, které dovolí webovému rozhraní komunikovat se serverem."""
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'X-Requested-With, Content-Type')

    def do_OPTIONS(self):
        """Zpracuje tzv. "pre-flight" požadavek od prohlížeče."""
        self.send_response(200, "ok")
        self._send_cors_headers()
        self.end_headers()

    def do_POST(self):
        """Tato metoda se zavolá, když přijde zpráva z webového rozhraní."""
        try:
            # 1. Přečteme délku příchozích dat
            content_length = int(self.headers['Content-Length'])
            
            # 2. Načteme samotná data
            post_data = self.rfile.read(content_length)
            
            # 3. Převedeme data z formátu JSON na Python slovník (dictionary)
            data_dict = json.loads(post_data)
            
            # --- ZDE SE DĚJE TO KOUZLO ---
            print("="*30)
            print("🎉 ZPRÁVA ÚSPĚŠNĚ ZACHYCENA 🎉")
            print("Přijatá data ve formátu JSON:")
            print(json.dumps(data_dict, indent=2, ensure_ascii=False))
            print("="*30)
            # --- ZDE BY V BUDOUCNU BYLA LOGIKA PRO ZPRACOVÁNÍ ---
            # Např. volání AI agenta, práce se soubory atd.
            
            # 4. Odešleme odpověď zpět do webového rozhraní
            self.send_response(200)
            self._send_cors_headers()
            self.end_headers()
            
            # Můžeme poslat i nějaká data zpět, např. potvrzení
            response_message = {'status': 'success', 'message': 'Data byla úspěšně přijata'}
            self.wfile.write(json.dumps(response_message).encode('utf-8'))
            
        except Exception as e:
            print(f"❌ Chyba při zpracování požadavku: {e}")
            self.send_response(500)
            self.end_headers()
            self.wfile.write(b"Internal Server Error")

# Funkce pro spuštění serveru
def run_server():
    server_address = (HOST, PORT)
    httpd = HTTPServer(server_address, RequestHandler)
    print(f"✅ HTTP server spuštěn na http://{HOST}:{PORT}")
    print("Server naslouchá a čeká na zprávy z 'Claude Relay Bridge'...")
    httpd.serve_forever()

if __name__ == '__main__':
    run_server()