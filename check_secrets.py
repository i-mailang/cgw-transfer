#!/usr/bin/env python3
"""Check whether the cgw service identity can read secrets.env.

Run as root:  python3 /tmp/check_secrets.py
It drops to uid/gid 994/982 (cgw) and tries to open the file, reporting the
exact errno. This isolates file-permission problems from systemd sandbox ones.
"""
import os
import pwd
import sys

SECRETS = "/opt/services/data/compute-gateway/secrets.env"
TARGET_UID = 994
TARGET_GID = 982


def main():
    print("=== as root ===")
    try:
        with open(SECRETS) as fh:
            print("  readable, first line:", fh.readline().strip()[:30])
    except OSError as exc:
        print("  FAILED:", exc)

    print("=== dropping to cgw (uid=%d gid=%d) ===" % (TARGET_UID, TARGET_GID))
    try:
        os.setgroups([])
        os.setgid(TARGET_GID)
        os.setuid(TARGET_UID)
    except OSError as exc:
        print("  cannot drop privileges:", exc)
        return 1

    print("  now uid=%d gid=%d" % (os.getuid(), os.getgid()))
    try:
        with open(SECRETS) as fh:
            first = fh.readline().strip()
        print("  readable, first line:", first[:30])
        print("  VERDICT: cgw CAN read secrets.env")
        return 0
    except OSError as exc:
        print("  FAILED: errno=%d %s" % (exc.errno, exc.strerror))
        print("  VERDICT: cgw CANNOT read secrets.env")
        st = os.stat(SECRETS)
        print("  file mode: %o  uid=%d gid=%d" % (st.st_mode & 0o777,
                                                  st.st_uid, st.st_gid))
        return 1


if __name__ == "__main__":
    sys.exit(main())
