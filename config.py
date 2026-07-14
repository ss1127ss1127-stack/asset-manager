"""アプリ全体で共有する設定値。

ライフプラン拡張を見据えて、シート名・列名・資産分類などの
「変わりやすい値」をすべてここに集約しておく。
"""

from datetime import date
from pathlib import Path

# --- Google Sheets ---------------------------------------------------------
SPREADSHEET_ID = "1Gb4Ze8X3hFw4U1fHBQd_G5oQwhCOROkpVAsumS67uS0"

# 作業ディレクトリにあるサービスアカウント鍵
CREDENTIALS_PATH = Path(__file__).resolve().parent / "credentials.json"

# サービスアカウントに付与するスコープ。
# open_by_key による読み書きは Sheets API だけで完結するため、
# spreadsheets スコープのみとする（Drive API の有効化は不要）。
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

# --- シート構成 ------------------------------------------------------------
DATABASE_SHEET = "データベース"
MASTER_SHEET = "マスタ"

# データベースシートの列（この順序で APPEND する）
COL_YEAR_MONTH = "年月"
COL_OWNER = "名義"
COL_ACCOUNT = "口座名"
COL_CATEGORY = "カテゴリ"
COL_AMOUNT = "金額"
COL_NOTE = "備考"

DATABASE_COLUMNS = [
    COL_YEAR_MONTH,
    COL_OWNER,
    COL_ACCOUNT,
    COL_CATEGORY,
    COL_AMOUNT,
    COL_NOTE,
]

# 入力フォームの選択肢として読み込む論理項目
MASTER_COLUMNS = [COL_OWNER, COL_ACCOUNT, COL_CATEGORY]

# マスタシート側の実際の見出し名。シートでは「〜マスタ」の接尾辞が付く。
# 見出しが見つからない場合は論理名（COL_*）にフォールバックする。
MASTER_HEADERS = {
    COL_OWNER: "名義マスタ",
    COL_ACCOUNT: "口座名マスタ",
    COL_CATEGORY: "カテゴリマスタ",
}

# --- 資産分類（安全資産 vs リスク資産）-------------------------------------
# カテゴリ名にこれらのキーワードが含まれるかで判定する。
# 完全一致ではなく部分一致なので「普通預金」「定期預金」なども安全資産になる。
# 注意: リスク資産の判定を先に行う（「投資信託の現金部分」等の誤判定を避けるため
# analytics.classify_asset はリスク→安全の順で評価する）。
SAFE_ASSET_KEYWORDS = ["現金", "預金", "貯金", "普通", "定期", "MRF", "保険"]
RISK_ASSET_KEYWORDS = [
    "投資", "投信", "信託", "株", "ETF", "債券", "FX",
    "暗号", "仮想", "REIT",
]

# --- シミュレーション既定値 ------------------------------------------------
DEFAULT_ANNUAL_RATE = 0.05  # 年利5%
DEFAULT_PROJECTION_YEARS = 20


# ===========================================================================
#  ライフプランシミュレーション
# ===========================================================================
# 専用シート。無い場合はデフォルト値で自動作成する（gsheet.load_sim_settings）。
SIM_SETTINGS_SHEET = "シミュレーション設定"
SIM_KEY_COL = "項目"
SIM_VALUE_COL = "値"

# ユーザーがサイドバーで調整した入力値一式を保存する専用シート。
# セル A1 に状態を JSON 文字列で丸ごと保持し、起動時に初期値として読み込む。
SIM_STATE_SHEET = "ライフプラン入力"
SIM_STATE_CELL = "A1"

# --- 生活費 ---------------------------------------------------------------
# 「基本生活費」（夫婦の食費・光熱費等のベース）月額の初期値。
# 子どもの養育費は別途 CHILDCARE_BRACKETS で自動加算する。
DEFAULT_LIVING_COST_MONTHLY = 310_000          # 現役
DEFAULT_RETIRE_LIVING_COST_MONTHLY = 250_000   # リタイア後
# リタイア後は現役時代の何割で暮らすか（参考値。既定は上記の実額を使用）。
RETIRE_LIVING_RATIO = 0.7

# --- 収入 -----------------------------------------------------------------
# 世帯の年間手取り収入（現役時代）と、年金の初期値。
# DEFAULT_PENSION_MONTHLY は「65歳受給開始を基準（±0%）とした月額」。
# 実際の受給額は受給開始年齢に応じて自動増減する（PENSION_* / lifeplan.pension_factor）。
DEFAULT_ANNUAL_INCOME = 6_000_000  # 手取り 600万円/年
DEFAULT_PENSION_MONTHLY = 200_000  # 65歳時点のベース月額
# 退職金（一時収入）
DEFAULT_SEVERANCE_AGE = 50
DEFAULT_SEVERANCE_AMOUNT = 0

# --- 年金（受給開始年齢による自動増減）------------------------------------
# 65歳時点の受給額をベース（±0%）とし、開始を早める/遅らせると増減する。
PENSION_BASE_AGE = 65                    # 増減の基準年齢（この年齢開始で係数1.0）
PENSION_DEFER_RATE_PER_MONTH = 0.007     # 繰り下げ: 1ヶ月ごとに +0.7%（70歳で+42%）
PENSION_EARLY_RATE_PER_MONTH = 0.004     # 繰り上げ: 1ヶ月ごとに -0.4%（60歳で-24%）

# 「年金額を概算する」ボタンの簡易式パラメータ。
PENSION_BASIC_MONTHLY_COUPLE = 130_000   # 基礎年金（夫婦2人分）月額・一律
PENSION_KOSEI_COEFF = 5.481 / 1000       # 厚生年金の乗率（報酬比例部分）
PENSION_TAKEHOME_TO_GROSS = 0.8          # 手取り→額面の逆算係数（手取り = 額面×0.8 と仮定）
PENSION_WORK_START_AGE = 22              # 就労開始年齢（加入期間 = リタイア年齢 − この値）

# --- 定例支出: 持家修繕・家電買い換え（固定計上）--------------------------
# 夫（本人）が HOME_MAINTENANCE_START_AGE 歳の年から
# HOME_MAINTENANCE_INTERVAL 年ごとに HOME_MAINTENANCE_AMOUNT を年間支出へ上乗せ。
HOME_MAINTENANCE_START_AGE = 35
HOME_MAINTENANCE_INTERVAL = 10
HOME_MAINTENANCE_AMOUNT = 1_500_000
COL_HOME_MAINTENANCE = "持家修繕・家電買い換え"

# --- 定例支出: 子どもの大学卒業（独立）時支出 ------------------------------
# 各子どもが CHILD_INDEPENDENCE_AGE 歳になる年に CHILD_INDEPENDENCE_AMOUNT を計上。
CHILD_INDEPENDENCE_AGE = 22
CHILD_INDEPENDENCE_AMOUNT = 1_000_000
COL_CHILD_INDEPENDENCE = "子ども大学卒業時支出"

# --- 運用利回り（リタイア前後で切替）--------------------------------------
DEFAULT_RATE_BEFORE = 0.05  # リタイア前 年利5%
DEFAULT_RATE_AFTER = 0.03   # リタイア後 年利3%

# --- ライフイベント目標 ----------------------------------------------------
DEFAULT_RETIRE_AGE = 50
DEFAULT_PENSION_START_AGE = 70  # 年金受給開始年齢（リタイアと分離）
DEFAULT_CURRENT_AGE = 40  # 本人（世帯主）の現在年齢の初期値
LIFE_END_AGE = 90  # シミュレーションの終端年齢

# --- 住居費（住宅ローン、変動金利対応）------------------------------------
DEFAULT_HOUSING_CURRENT_MONTHLY = 72_153   # 現在の月々支払額
DEFAULT_HOUSING_REVISED_MONTHLY = 90_000   # 金利見直し後の月々支払額
DEFAULT_HOUSING_REVISE_AGE = 35            # 見直しが適用される年齢
DEFAULT_HOUSING_END_AGE = 61               # ローン支払い終了年齢（例: 2054年＝夫61歳）

# --- 養育費（子の年齢に応じた年間加算額）----------------------------------
# (下限年齢, 上限年齢, 年間加算額) いずれも含む。範囲外（23歳以上）は 0。
CHILDCARE_BRACKETS = [
    (0, 6, 120_000),    # 未就学: 月1万
    (7, 12, 240_000),   # 小学生: 月2万
    (13, 15, 420_000),  # 中学生: 月3.5万
    (16, 22, 600_000),  # 高校・大学生: 月5万
]

# --- 児童手当（第3子以降の増額に対応）------------------------------------
CHILD_ALLOWANCE_MAX_AGE = 18            # 高校生年代（18歳）まで
CHILD_ALLOWANCE_UNDER3_MONTHLY = 15_000  # 3歳未満（第1・2子）
CHILD_ALLOWANCE_STD_MONTHLY = 10_000     # 3歳〜18歳（第1・2子）
CHILD_ALLOWANCE_THIRD_MONTHLY = 30_000   # 第3子以降（0〜18歳）

# --- 多子世帯の大学無償化 --------------------------------------------------
# 扶養する子が MULTI_CHILD_THRESHOLD 人以上いる年は、大学生の授業料を免除扱いにする。
MULTI_CHILD_THRESHOLD = 3
DEPENDENT_MAX_AGE = 22  # 扶養とみなす上限年齢

# 支援制度チェックボックスの初期状態
DEFAULT_APPLY_CHILD_ALLOWANCE = True
DEFAULT_APPLY_UNIV_FREE_MULTI = True

# --- 本人・子どもの生年月日 ------------------------------------------------
# 年齢の初期値は「今日」から自動計算する（age_on）。
BIRTHDATE_SELF = date(1992, 11, 27)
CHILDREN = ["長男", "次男", "三男"]
CHILD_BIRTHDATES = {
    "長男": date(2020, 7, 5),
    "次男": date(2022, 9, 10),
    "三男": date(2026, 4, 15),
}


def age_on(birthdate: date, today: date | None = None) -> int:
    """誕生日基準の満年齢を返す（today 省略時は本日）。"""
    today = today or date.today()
    had_birthday = (today.month, today.day) >= (birthdate.month, birthdate.day)
    return today.year - birthdate.year - (0 if had_birthday else 1)


# --- 教育ステージと年齢範囲（日本の標準的な学齢）--------------------------
# (下限年齢, 上限年齢) いずれも含む。範囲外は教育費0。
EDUCATION_STAGES = ["小学校", "中学校", "高校", "大学"]
SCHOOL_TYPES = ["公立", "私立"]
STAGE_AGE_RANGE = {
    "小学校": (6, 11),
    "中学校": (12, 14),
    "高校": (15, 17),
    "大学": (18, 21),
}

# 各ステージの公立/私立の初期選択（大学のみ私立、他は公立）。
DEFAULT_SCHOOL_CHOICE = {
    "小学校": "公立",
    "中学校": "公立",
    "高校": "公立",
    "大学": "私立",
}

# 各ステージ・公立/私立ごとの「年間」教育費（円）の初期値。
# 出典目安: 文科省「子供の学習費調査」/ 大学は授業料＋諸経費の概算。
DEFAULT_EDUCATION_COST = {
    ("小学校", "公立"): 350_000,
    ("小学校", "私立"): 1_670_000,
    ("中学校", "公立"): 540_000,
    ("中学校", "私立"): 1_440_000,
    ("高校", "公立"): 510_000,
    ("高校", "私立"): 1_050_000,
    ("大学", "公立"): 800_000,
    ("大学", "私立"): 1_500_000,
}


def edu_key(stage: str, school_type: str) -> str:
    """教育費設定のキー名（シートの『項目』列と対応）。例: 小学校_公立"""
    return f"{stage}_{school_type}"


def default_sim_settings() -> dict[str, float]:
    """シミュレーション設定のデフォルト値を項目→数値の辞書で返す。

    『シミュレーション設定』シートが無い/欠損しているときの土台になる。
    """
    settings: dict[str, float] = {
        "平均生活費（月額）": float(DEFAULT_LIVING_COST_MONTHLY),
    }
    for stage in EDUCATION_STAGES:
        for school_type in SCHOOL_TYPES:
            key = edu_key(stage, school_type)
            settings[key] = float(DEFAULT_EDUCATION_COST[(stage, school_type)])
    return settings
