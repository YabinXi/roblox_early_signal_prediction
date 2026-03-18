"""
prepare.py — Universal data standardization layer (read-only, not modified by agents)

Reads raw data files from data/raw/, standardizes formats, outputs CSVs to
data/processed/ and a data_snapshot.json summary.

Usage: uv run python prepare.py

Customize the `LOADERS` dict to add domain-specific data loading logic.
"""

import json
import warnings
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore", category=UserWarning)

# === Path configuration ===
BASE_DIR = Path(__file__).parent
RAW_DIR = BASE_DIR / "data" / "raw"
PROC_DIR = BASE_DIR / "data" / "processed"
SNAPSHOT_PATH = BASE_DIR / "data" / "data_snapshot.json"

PROC_DIR.mkdir(parents=True, exist_ok=True)


def load_csv_auto(filename: str, **kwargs) -> pd.DataFrame:
    """Load a CSV with automatic encoding detection."""
    path = RAW_DIR / filename
    if not path.exists():
        print(f"  [SKIP] {filename} not found")
        return pd.DataFrame()

    for encoding in ["utf-8", "utf-8-sig", "utf-16", "utf-16-le", "gbk", "latin-1"]:
        for sep in [",", "\t", ";"]:
            try:
                df = pd.read_csv(path, encoding=encoding, sep=sep, **kwargs)
                if len(df.columns) > 1:
                    return df
            except Exception:
                continue

    print(f"  [ERROR] Could not parse {filename}")
    return pd.DataFrame()


def load_excel_auto(filename: str, **kwargs) -> pd.DataFrame:
    """Load an Excel file with automatic header detection."""
    path = RAW_DIR / filename
    if not path.exists():
        print(f"  [SKIP] {filename} not found")
        return pd.DataFrame()

    try:
        df = pd.read_excel(path, engine="openpyxl", **kwargs)
        return df
    except Exception as e:
        print(f"  [ERROR] {filename}: {e}")
        return pd.DataFrame()


def standardize_dates(df: pd.DataFrame, date_col: str = "date") -> pd.DataFrame:
    """Ensure date column is datetime type."""
    if date_col in df.columns:
        df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
    return df


def build_snapshot(datasets: dict) -> dict:
    """Generate data snapshot JSON summarizing all datasets."""
    snapshot = {
        "generated_at": datetime.now().isoformat(),
        "datasets": {},
    }

    for name, df in datasets.items():
        if df is None or df.empty:
            snapshot["datasets"][name] = {"status": "empty", "rows": 0}
            continue

        info = {
            "rows": len(df),
            "columns": list(df.columns),
            "dtypes": {col: str(dtype) for col, dtype in df.dtypes.items()},
        }

        # Date range
        if "date" in df.columns:
            dates = df["date"].dropna()
            if len(dates) > 0:
                info["date_range"] = {
                    "min": str(dates.min().date()),
                    "max": str(dates.max().date()),
                }

        # Numeric summary
        num_cols = df.select_dtypes(include=[np.number]).columns.tolist()
        if num_cols:
            desc = df[num_cols].describe()
            info["numeric_summary"] = {}
            for col in num_cols:
                info["numeric_summary"][col] = {
                    "mean": round(float(desc.loc["mean", col]), 2) if not pd.isna(desc.loc["mean", col]) else None,
                    "std": round(float(desc.loc["std", col]), 2) if not pd.isna(desc.loc["std", col]) else None,
                    "min": round(float(desc.loc["min", col]), 2) if not pd.isna(desc.loc["min", col]) else None,
                    "max": round(float(desc.loc["max", col]), 2) if not pd.isna(desc.loc["max", col]) else None,
                }

        snapshot["datasets"][name] = info

    return snapshot


def main():
    print("=" * 60)
    print("AutoResearch — Data Preparation")
    print("=" * 60)

    datasets = {}

    # === Auto-discover and load files ===
    print("\nScanning data/raw/ for files...")

    if not RAW_DIR.exists():
        print(f"  [WARN] {RAW_DIR} does not exist. Create it and add data files.")
        RAW_DIR.mkdir(parents=True, exist_ok=True)
        return

    # Load CSVs
    for csv_file in sorted(RAW_DIR.glob("*.csv")):
        name = csv_file.stem
        print(f"  Loading {csv_file.name}...")
        df = load_csv_auto(csv_file.name)
        if not df.empty:
            df = standardize_dates(df)
            datasets[name] = df
            df.to_csv(PROC_DIR / f"{name}.csv", index=False)
            print(f"    ✓ {name}: {len(df)} rows, {len(df.columns)} columns")

    # Load Excel files
    for xl_file in sorted(RAW_DIR.glob("*.xlsx")):
        name = xl_file.stem
        print(f"  Loading {xl_file.name}...")
        df = load_excel_auto(xl_file.name)
        if not df.empty:
            df = standardize_dates(df)
            datasets[name] = df
            df.to_csv(PROC_DIR / f"{name}.csv", index=False)
            print(f"    ✓ {name}: {len(df)} rows, {len(df.columns)} columns")

    # Load JSON files
    for json_file in sorted(RAW_DIR.glob("*.json")):
        name = json_file.stem
        print(f"  Loading {json_file.name}...")
        try:
            with open(json_file, "r", encoding="utf-8") as f:
                json_data = json.load(f)
            # If it's a list of records, convert to DataFrame
            if isinstance(json_data, list):
                df = pd.DataFrame(json_data)
                df = standardize_dates(df)
                datasets[name] = df
                df.to_csv(PROC_DIR / f"{name}.csv", index=False)
                print(f"    ✓ {name}: {len(df)} rows")
            else:
                # Store as-is in snapshot
                datasets[name] = pd.DataFrame()  # placeholder
                print(f"    ✓ {name}: JSON object (not tabular)")
        except Exception as e:
            print(f"    [ERROR] {e}")

    # Build snapshot
    print("\nBuilding data snapshot...")
    snapshot = build_snapshot(datasets)

    with open(SNAPSHOT_PATH, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, ensure_ascii=False, indent=2)

    print(f"\n✓ Snapshot saved to {SNAPSHOT_PATH}")
    print(f"  Datasets: {len(snapshot['datasets'])}")
    for name, info in snapshot["datasets"].items():
        rows = info.get("rows", 0)
        date_range = info.get("date_range", {})
        dr_str = f" ({date_range['min']} → {date_range['max']})" if date_range else ""
        print(f"  • {name}: {rows} rows{dr_str}")

    print("\n" + "=" * 60)
    print("Data preparation complete!")
    print("=" * 60)


if __name__ == "__main__":
    main()
