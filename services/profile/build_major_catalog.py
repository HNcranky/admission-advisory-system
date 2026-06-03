import sys

from services.profile.major_catalog import build_major_catalog


def main() -> int:
    report = build_major_catalog()
    print(f"program catalog: total={report.total} embedded={report.embedded} reused={report.reused}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
