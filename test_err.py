import urllib.request
try:
    urllib.request.urlopen("http://127.0.0.1:8000/api/servicios-nativos/")
except Exception as e:
    with open('t.html', 'w') as f:
        f.write(e.read().decode())
