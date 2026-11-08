"""Re-encrypt every stored Meta token under the current TOKEN_ENCRYPTION_KEY.

Run after moving the previous key to TOKEN_ENCRYPTION_KEY_OLD (see
token_crypto.py). A dry run by default — it reports what it would change;
pass --apply to write. Each tenant's rows are rotated in that tenant's own
transaction, so row-level security sees them as it does for the app.

    python scripts/rotate_tokens.py            # dry run
    python scripts/rotate_tokens.py --apply
"""
from __future__ import annotations

import sys
from pathlib import Path
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from db.session import get_pool, tenant_connection  # noqa: E402
from token_crypto import TokenCryptoError, rotate  # noqa: E402

COLUMNS = ("encrypted_access_token", "selected_page_access_token")


def main(apply: bool) -> int:
    with get_pool().connection() as conn:
        tenants = [r[0] for r in conn.execute("select distinct tenant_id from meta_connections").fetchall()]
    done = failed = 0
    for tenant in tenants:
        with tenant_connection(UUID(str(tenant))) as conn:
            for row_id, *values in conn.execute(f"select id, {', '.join(COLUMNS)} from meta_connections").fetchall():
                fresh = {}
                for col, value in zip(COLUMNS, values):
                    if value is None:
                        continue
                    try:
                        fresh[col] = rotate(value)
                    except TokenCryptoError as e:
                        failed += 1
                        print(f"  {row_id} {col}: {e}")
                if fresh and apply:
                    sets = ", ".join(f"{c} = %s" for c in fresh)
                    conn.execute(f"update meta_connections set {sets}, updated_at = now() where id = %s", (*fresh.values(), row_id))
                done += len(fresh)
    print(f"{'rotated' if apply else 'would rotate'} {done} token(s) across {len(tenants)} tenant(s); {failed} could not be read")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main("--apply" in sys.argv))
