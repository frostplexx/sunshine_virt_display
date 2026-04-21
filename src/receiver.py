import subprocess
import socket
import os

BASE_DIR = os.path.dirname(os.path.realpath(__file__))

SOCKET_FILE = "/tmp/sunshineVD.sock"
MAIN_PY_PATH = os.path.join(BASE_DIR, "main.py")

# 1. Clean up the socket file if it already exists from a previous run
if os.path.exists(SOCKET_FILE):
    os.remove(SOCKET_FILE)

# 2. Create the socket (AF_UNIX means local file, SOCK_STREAM means continuous data)
server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)

server.bind(SOCKET_FILE)
os.chmod(SOCKET_FILE, 0o666)  # Make it accessible to Sunshine
server.listen(1)

print("Daemon is waiting...")

while True:
    # 4. Accept a connection (This "blocks"/sleeps until someone connects)
    connection, client_address = server.accept()
    try:
        # 5. Read the data (64 is the buffer size)
        data = connection.recv(128)
        if data:
            args = data.decode('utf-8').split(',')
            print("received : {args}")
            subprocess.run(["/usr/bin/python3", MAIN_PY_PATH] + args)
    finally:
        # 6. Always close the connection when done
        connection.close()
