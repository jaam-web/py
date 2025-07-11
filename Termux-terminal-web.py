import os
import pty
import tornado.ioloop
import tornado.web
import tornado.websocket
import termios
import fcntl
import struct
import signal
import argparse
import urllib.request
import uuid
import hashlib
import json

# --- Configuración inicial ---
DIRECTORIO_RECURSOS = "recursos_web"
os.makedirs(DIRECTORIO_RECURSOS, exist_ok=True)

# --- Clase WebSocket mejorada ---
class TerminalWebSocket(tornado.websocket.WebSocketHandler):
    def initialize(self, app_password_hash):
        self.pty = None
        self.fd = None
        self.child_pid = None
        self.authenticated = False
        self.session_id = None
        self.app_password_hash = app_password_hash

    def open(self):
        self.session_id = self.get_argument("session_id", None)
        if not self.session_id:
            self.close()
            return

        if self.session_id in AUTHENTICATED_SESSIONS:
            self._start_terminal_session()
        else:
            self.write_message(json.dumps({"type": "auth", "status": "required"}))

    def _start_terminal_session(self):
        self.authenticated = True
        AUTHENTICATED_SESSIONS[self.session_id] = True

        env = os.environ.copy()
        env.update({
            'TERM': 'xterm-256color',
            'COLORTERM': 'truecolor',
            'SHELL': 'bash',
            'LANG': 'en_US.UTF-8'
        })

        try:
            pid, fd = pty.fork()
            if pid == 0:
                os.execvpe('bash', ['bash', '--login'], env)
            else:
                self.fd = fd
                self.child_pid = pid
                self._set_pty_size(40, 120)

                flags = fcntl.fcntl(self.fd, fcntl.F_GETFL)
                fcntl.fcntl(self.fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)

                tornado.ioloop.IOLoop.current().add_handler(
                    self.fd, self._handle_read, tornado.ioloop.IOLoop.READ)
                
                self.write_message(json.dumps({
                    "type": "auth", 
                    "status": "success"
                }))
                
        except Exception as e:
            self.write_message(json.dumps({
                "type": "error",
                "message": f"No se pudo iniciar la terminal: {str(e)}"
            }))
            self.close()

    def on_message(self, message):
        try:
            msg = json.loads(message)
            
            if not self.authenticated:
                if msg.get("type") == "auth" and "password" in msg:
                    input_hash = hashlib.sha256(msg["password"].encode()).hexdigest()
                    if input_hash == self.app_password_hash:
                        self._start_terminal_session()
                    else:
                        self.write_message(json.dumps({
                            "type": "auth",
                            "status": "failed",
                            "message": "Contraseña incorrecta"
                        }))
                return
            
            if msg.get("type") == "resize":
                self._set_pty_size(msg["rows"], msg["cols"])
            elif "data" in msg:
                if self.fd:
                    os.write(self.fd, msg["data"].encode())
                    
        except json.JSONDecodeError:
            if self.fd and self.authenticated:
                os.write(self.fd, message.encode())

    def _set_pty_size(self, rows, cols):
        if self.fd:
            try:
                size = struct.pack("HHHH", rows, cols, 0, 0)
                fcntl.ioctl(self.fd, termios.TIOCSWINSZ, size)
            except Exception as e:
                print(f"Error al cambiar tamaño: {e}")

    def _handle_read(self, fd, events):
        try:
            data = os.read(fd, 1024 * 20)
            if data:
                self.write_message(json.dumps({
                    "type": "data",
                    "data": data.decode()
                }))
            else:
                self.close()
        except (OSError, tornado.websocket.WebSocketClosedError):
            self.close()

    def on_close(self):
        if self.fd:
            tornado.ioloop.IOLoop.current().remove_handler(self.fd)
            os.close(self.fd)
        if self.child_pid:
            try:
                os.kill(self.child_pid, signal.SIGTERM)
                os.waitpid(self.child_pid, 0)
            except ProcessLookupError:
                pass

# --- Manejador principal ---
class MainHandler(tornado.web.RequestHandler):
    def get(self):
        self.render("terminal.html")

# --- Aplicación ---
def make_app(password):
    password_hash = hashlib.sha256(password.encode()).hexdigest()
    
    return tornado.web.Application([
        (r"/", MainHandler),
        (r"/ws", TerminalWebSocket, {"app_password_hash": password_hash}),
        (r"/static/(.*)", tornado.web.StaticFileHandler, {"path": DIRECTORIO_RECURSOS}),
    ], template_path=DIRECTORIO_RECURSOS)

# --- HTML mejorado ---
TERMINAL_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>Terminal Web</title>
    <meta charset="utf-8">
    <style>
        body { 
            margin: 0; 
            padding: 0; 
            background: #000;
            color: #fff;
            font-family: monospace;
        }
        #terminal-container {
            width: 100%;
            height: 100vh;
            padding: 10px;
            box-sizing: border-box;
        }
        #auth-container {
            position: fixed;
            top: 50%;
            left: 50%;
            transform: translate(-50%, -50%);
            background: #222;
            padding: 20px;
            border-radius: 5px;
            text-align: center;
        }
        #auth-message {
            color: #f55;
            margin-top: 10px;
        }
    </style>
    <script>
        document.addEventListener('DOMContentLoaded', () => {
            const authContainer = document.getElementById('auth-container');
            const terminalContainer = document.getElementById('terminal-container');
            const passwordInput = document.getElementById('password-input');
            const authButton = document.getElementById('auth-button');
            const authMessage = document.getElementById('auth-message');
            
            let sessionId = localStorage.getItem('terminal_session_id');
            if (!sessionId) {
                sessionId = crypto.randomUUID();
                localStorage.setItem('terminal_session_id', sessionId);
            }
            
            const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
            const ws = new WebSocket(`${protocol}//${window.location.host}/ws?session_id=${sessionId}`);
            
            ws.onmessage = (event) => {
                const msg = JSON.parse(event.data);
                
                if (msg.type === 'auth') {
                    if (msg.status === 'required') {
                        authContainer.style.display = 'block';
                    } 
                    else if (msg.status === 'success') {
                        authContainer.style.display = 'none';
                        terminalContainer.style.display = 'block';
                        initTerminal();
                    }
                    else if (msg.status === 'failed') {
                        authMessage.textContent = msg.message || 'Autenticación fallida';
                    }
                }
                else if (msg.type === 'data' && terminal) {
                    terminal.write(msg.data);
                }
            };
            
            authButton.addEventListener('click', () => {
                const password = passwordInput.value.trim();
                if (password) {
                    ws.send(JSON.stringify({
                        type: 'auth',
                        password: password
                    }));
                }
            });
            
            passwordInput.addEventListener('keypress', (e) => {
                if (e.key === 'Enter') {
                    authButton.click();
                }
            });
            
            let terminal;
            function initTerminal() {
                terminal = new Terminal();
                terminal.open(terminalContainer);
                
                terminal.onData(data => {
                    ws.send(JSON.stringify({
                        type: 'data',
                        data: data
                    }));
                });
                
                terminal.onResize(size => {
                    ws.send(JSON.stringify({
                        type: 'resize',
                        rows: size.rows,
                        cols: size.cols
                    }));
                });
                
                terminal.focus();
            }
        });
    </script>
</head>
<body>
    <div id="auth-container" style="display: none;">
        <h2>Autenticación Requerida</h2>
        <input type="password" id="password-input" placeholder="Contraseña">
        <button id="auth-button">Acceder</button>
        <div id="auth-message"></div>
    </div>
    <div id="terminal-container" style="display: none;"></div>
    
    <script src="https://cdn.jsdelivr.net/npm/xterm@5.1.0/lib/xterm.min.js"></script>
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/xterm@5.1.0/css/xterm.min.css">
</body>
</html>
"""

# --- Ejecución ---
AUTHENTICATED_SESSIONS = {}

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8888)
    parser.add_argument('--password', required=True)
    args = parser.parse_args()

    # Guardar el HTML
    with open(os.path.join(DIRECTORIO_RECURSOS, 'terminal.html'), 'w') as f:
        f.write(TERMINAL_HTML)

    app = make_app(args.password)
    app.listen(args.port)
    print(f"Servidor iniciado en http://localhost:{args.port}")
    tornado.ioloop.IOLoop.current().start()

if __name__ == "__main__":
    main()
