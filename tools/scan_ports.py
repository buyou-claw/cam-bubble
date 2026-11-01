import socket, sys, concurrent.futures

def probe(ip, port, timeout=0.35):
    s = socket.socket()
    s.settimeout(timeout)
    try:
        if s.connect_ex((ip, port)) == 0:
            return port
    except Exception:
        pass
    finally:
        s.close()
    return None

def scan(ip, lo, hi, workers=600):
    open_ports = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        futs = [ex.submit(probe, ip, p) for p in range(lo, hi + 1)]
        for f in concurrent.futures.as_completed(futs):
            r = f.result()
            if r:
                open_ports.append(r)
    return sorted(open_ports)

if __name__ == "__main__":
    ip = sys.argv[1]
    lo = int(sys.argv[2]) if len(sys.argv) > 2 else 30000
    hi = int(sys.argv[3]) if len(sys.argv) > 3 else 50000
    print(f"scan {ip} {lo}-{hi} ...")
    ports = scan(ip, lo, hi)
    print("OPEN:", ", ".join(str(p) for p in ports) if ports else "(none)")
