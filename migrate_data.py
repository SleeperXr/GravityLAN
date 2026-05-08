import json
import sqlite3
import os
import argparse
from datetime import datetime

def export_data(db_path, output_path):
    if not os.path.exists(db_path):
        print(f"Error: Database not found at {db_path}")
        return

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    data = {
        "metadata": {
            "exported_at": datetime.now().isoformat(),
            "version": "0.1.0"
        },
        "device_groups": [],
        "devices": [],
        "services": [],
        "discovered_hosts": [],
        "settings": []
    }

    # Export tables
    tables = {
        "device_groups": "device_groups",
        "devices": "devices",
        "services": "services",
        "discovered_hosts": "discovered_hosts",
        "settings": "settings",
        "agent_tokens": "agent_tokens",
        "agent_configs": "agent_configs"
    }

    for key, table in tables.items():
        try:
            cursor.execute(f"SELECT * FROM {table}")
            rows = cursor.fetchall()
            data[key] = [dict(row) for row in rows]
            print(f"Exported {len(data[key])} rows from {table}")
        except sqlite3.OperationalError as e:
            print(f"Warning: Table {table} skipped ({e})")

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    print(f"\nSuccessfully exported data to {output_path}")
    conn.close()

def import_data(db_path, input_path):
    if not os.path.exists(input_path):
        print(f"Error: Input file not found at {input_path}")
        return

    with open(input_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Disable foreign keys temporarily for bulk import
    cursor.execute("PRAGMA foreign_keys = OFF")

    for key, rows in data.items():
        if key == "metadata" or not rows:
            continue
        
        table = key
        if not rows:
            continue
            
        # Get target table columns
        cursor.execute(f"PRAGMA table_info({table})")
        # col_info: (id, name, type, notnull, dflt_value, pk)
        table_info = {col[1]: {"notnull": col[3], "default": col[4], "type": col[2]} for col in cursor.fetchall()}
        table_cols = set(table_info.keys())
        
        if not table_cols:
            print(f"Warning: Table {table} does not exist in target DB. Skipping.")
            continue

        print(f"Processing table {table} (Cols: {list(table_cols)})")

        valid_rows = []
        now_str = datetime.now().isoformat().replace("T", " ")

        for row in rows:
            clean_row = {}
            # Special Mapping: is_virtual (Old) -> virtual_type (New)
            if "is_virtual" in row and "virtual_type" in table_cols:
                if row["is_virtual"] and not row.get("virtual_type"):
                    row["virtual_type"] = "vm"
            
            # 1. Add existing valid columns, but filter out NULLs for NOT NULL fields
            for col, val in row.items():
                if col in table_cols:
                    if val is None and table_info[col]["notnull"]:
                        continue # Let step 2 handle it
                    clean_row[col] = val
            
            # 2. Force fill ALL missing or skipped mandatory columns
            for col, info in table_info.items():
                if info["notnull"] and (col not in clean_row or clean_row[col] is None):
                    # Column is required but missing or was NULL in JSON
                    if "DATETIME" in info["type"].upper() or "TIMESTAMP" in info["type"].upper():
                        clean_row[col] = now_str
                    elif "INT" in info["type"].upper() or "BOOLEAN" in info["type"].upper():
                        clean_row[col] = 0
                    else:
                        clean_row[col] = ""
            
            valid_rows.append(clean_row)

        if not valid_rows:
            continue

        # ENFORCE STRICT COLUMN ORDERING
        columns = list(valid_rows[0].keys())
        placeholders = ", ".join(["?"] * len(columns))
        col_names = ", ".join(columns)
        
        # Clear existing data
        cursor.execute(f"DELETE FROM {table}")
        
        insert_query = f"INSERT INTO {table} ({col_names}) VALUES ({placeholders})"
        
        # Build values tuples following the strict column list
        values = []
        for row in valid_rows:
            values.append(tuple(row.get(col) for col in columns))
            
        cursor.executemany(insert_query, values)
        print(f"Imported {len(valid_rows)} rows into {table}")

    conn.commit()
    cursor.execute("PRAGMA foreign_keys = ON")
    conn.close()
    print(f"\nSuccessfully imported data to {db_path}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="GravityLAN Data Migration Tool")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Export command
    export_parser = subparsers.add_parser("export", help="Export DB to JSON")
    export_parser.add_argument("--db", default="backend/data/gravitylan.db", help="Path to source sqlite db")
    export_parser.add_argument("--out", default="gravitylan_export.json", help="Path to output JSON")

    # Import command
    import_parser = subparsers.add_parser("import", help="Import JSON to DB")
    import_parser.add_argument("--file", default="gravitylan_export.json", help="Path to input JSON")
    import_parser.add_argument("--db", default="backend/data/gravitylan.db", help="Path to target sqlite db")
    
    args = parser.parse_args()
    
    if args.command == "export":
        export_data(args.db, args.out)
    elif args.command == "import":
        import_data(args.db, args.file)
    else:
        parser.print_help()
