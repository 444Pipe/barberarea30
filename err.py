import urllib.request, json
try:
    urllib.request.urlopen('http://127.0.0.1:8000/api/servicios-nativos/')
except Exception as e:
    with open('err_out.txt', 'w', encoding='utf-8') as f:
        f.write(json.loads(e.read().decode())['trace'])
