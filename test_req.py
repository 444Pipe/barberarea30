import urllib.request, urllib.error, json, ssl

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

try:
    req = urllib.request.Request('https://area30barberclub.com/api/admin/bookings/1/reschedule/', data=b'{"date":"2026-05-22", "time":"15:30"}', headers={'Content-Type': 'application/json'})
    res = urllib.request.urlopen(req, context=ctx)
    print("SUCCESS")
    print(res.read())
except urllib.error.HTTPError as e:
    print(f"HTTP ERROR: {e.code}")
    print(e.read().decode('utf-8'))
except Exception as e:
    print(f"ERROR: {e}")
