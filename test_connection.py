"""スプレッドシートへの接続テスト。

    python test_connection.py

サービスアカウントで認証し、シート一覧・データ件数・マスタの選択肢を表示する。
"""

import sys

import config
import gsheet


def main() -> int:
    print("=" * 60)
    print(" 資産管理アプリ : Google Sheets 接続テスト")
    print("=" * 60)
    print(f"認証ファイル : {config.CREDENTIALS_PATH}")
    print(f"対象シートID : {config.SPREADSHEET_ID}")
    print("-" * 60)

    try:
        client = gsheet.get_client()
        print("[OK] サービスアカウント認証に成功しました。")
    except Exception as e:  # noqa: BLE001
        print(f"[NG] 認証に失敗しました: {e}")
        return 1

    try:
        ss = gsheet.get_spreadsheet(client)
        titles = [ws.title for ws in ss.worksheets()]
        print(f"[OK] スプレッドシートを開きました: 「{ss.title}」")
        print(f"     シート一覧: {titles}")
    except Exception as e:  # noqa: BLE001
        # gspread は 403 を中身の無い PermissionError に変換するため、
        # 元の APIError(__cause__) からメッセージを取り出して原因を切り分ける。
        detail = str(getattr(e, "__cause__", "") or e)
        print(f"[NG] スプレッドシートを開けませんでした ({type(e).__name__})")
        if detail:
            print(f"     詳細: {detail}")
        if "has not been used" in detail or "disabled" in detail:
            print("     → 原因: Google Sheets API が無効です。")
            print("       次のURLで有効化してください（プロジェクト所有者の操作が必要）:")
            print("       https://console.cloud.google.com/apis/library/sheets.googleapis.com"
                  f"?project={config.SPREADSHEET_ID and 'asset-app-500305'}")
        else:
            print("     → 原因: スプレッドシートが共有されていない可能性があります。")
            print("       共有設定で次のサービスアカウントを「編集者」に追加してください:")
            print("       asset-manager@asset-app-500305.iam.gserviceaccount.com")
        return 1

    # データベースシート
    try:
        df = gsheet.load_database(client)
        print(f"[OK] 『{config.DATABASE_SHEET}』を読み込みました: {len(df)} 行")
        if not df.empty:
            months = sorted(df[config.COL_YEAR_MONTH].unique())
            print(f"     年月の範囲: {months[0]} 〜 {months[-1]}（{len(months)} 時点）")
    except Exception as e:  # noqa: BLE001
        print(f"[NG] 『{config.DATABASE_SHEET}』を読み込めませんでした: {e}")

    # マスタシート
    try:
        masters = gsheet.load_masters(client)
        print(f"[OK] 『{config.MASTER_SHEET}』を読み込みました:")
        for col, values in masters.items():
            preview = "、".join(values[:5]) if values else "(空)"
            print(f"     - {col}: {len(values)} 件  例) {preview}")
    except Exception as e:  # noqa: BLE001
        print(f"[NG] 『{config.MASTER_SHEET}』を読み込めませんでした: {e}")

    print("-" * 60)
    print("接続テスト完了。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
