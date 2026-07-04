"""ライフプランシミュレーション（Streamlit マルチページ）。

既存ダッシュボード（app.py）とは独立したページ。専用サイドバーに調整UIを置き、
本体に サマリーカード / 資産推移＋年間支出グラフ / キャッシュフロー表 を描画する。

計算は lifeplan.py（純粋関数）、設定の読込は gsheet.load_sim_settings に委譲。
"""

from __future__ import annotations

from datetime import datetime

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st

import analytics
import config
import gsheet
import lifeplan

st.set_page_config(
    page_title="ライフプランシミュレーション",
    page_icon="🌱",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
      /* ルートを大きめにして全体（テキスト・ウィジェット・カード）を比例拡大 */
      html { font-size: 18px; }
      .block-container { padding-top: 2rem; padding-bottom: 2rem; }
      div[data-testid="stMetric"] {
        background: #f7f9fc; border: 1px solid #e6ebf2;
        border-radius: 14px; padding: 14px 18px;
      }
      div[data-testid="stMetricLabel"] { opacity: 0.7; }
      div[data-testid="stMetricValue"] { font-size: 1.9rem; }
      h1, h2, h3 { letter-spacing: .02em; }

      /* データフレームは横スクロールで全列を確認できるようにする */
      div[data-testid="stDataFrame"] { overflow-x: auto; }

      /* --- スマートフォン（縦長・狭幅）向け最適化 --- */
      @media (max-width: 640px) {
        html { font-size: 15px; }
        .block-container {
          padding-top: 1rem; padding-bottom: 1rem;
          padding-left: .6rem; padding-right: .6rem;
        }
        div[data-testid="stMetricValue"] { font-size: 1.4rem; }
        div[data-testid="stHorizontalBlock"] { flex-wrap: wrap; }
      }
    </style>
    """,
    unsafe_allow_html=True,
)

COLOR_ASSET = "#2E86DE"
COLOR_INCOME = "#27AE60"
COLOR_MILESTONE = "#8E44AD"
# 支出カテゴリの配色（積み上げ棒）
EXPENSE_COLORS = {
    "基本生活費": "#95A5A6",
    "住居費": "#34495E",
    "養育費": "#F1C40F",
    "教育費": "#E67E22",
    "カスタム支出": "#C0392B",
}


# --- データ取得（キャッシュ）----------------------------------------------
@st.cache_resource(show_spinner=False)
def get_client():
    return gsheet.get_client()


@st.cache_data(ttl=300, show_spinner="スプレッドシートを読み込み中…")
def load_all():
    client = get_client()
    df = gsheet.load_database(client)
    settings = gsheet.load_sim_settings(client)
    return df, settings


def yen(value: float) -> str:
    return f"¥{value:,.0f}"


# --- データ読み込み --------------------------------------------------------
st.title("🌱 ライフプランシミュレーション")

if st.sidebar.button("🔄 データを再読み込み", width="stretch"):
    load_all.clear()
    st.rerun()

try:
    df, settings = load_all()
except Exception as e:  # noqa: BLE001
    st.warning(
        "スプレッドシートに接続できませんでした。デフォルト値で続行します。\n\n"
        f"詳細: {getattr(e, '__cause__', '') or e}"
    )
    df, settings = pd.DataFrame(), config.default_sim_settings()

totals = analytics.monthly_total(df)
valid_totals = totals.dropna(subset=["_date"]) if not totals.empty else totals
if not valid_totals.empty:
    latest = valid_totals.iloc[-1]
    default_asset = float(latest["合計"])
    default_start_year = int(latest["_date"].year)
else:
    default_asset = 0.0
    default_start_year = datetime.now().year


# ===========================================================================
#  サイドバー: 調整パラメータ
# ===========================================================================
st.sidebar.title("⚙️ シミュレーション条件")

st.sidebar.subheader("👤 基本設定")
start_asset = float(st.sidebar.number_input(
    "現在の資産残高（初期資産）", min_value=0,
    value=int(default_asset), step=100_000, format="%d",
    help="資産管理ダッシュボードの最新月の総資産を初期値に参照しています。",
))
st.sidebar.caption(f"↑ ダッシュボード最新月の総資産: **{yen(default_asset)}**")
start_year = int(st.sidebar.number_input(
    "起点の西暦", min_value=2000, max_value=2100,
    value=default_start_year, step=1,
))
current_age = int(st.sidebar.number_input(
    "本人の現在年齢", min_value=0, max_value=90,
    value=config.age_on(config.BIRTHDATE_SELF), step=1,
    help=f"生年月日 {config.BIRTHDATE_SELF:%Y-%m-%d} から自動計算した満年齢を初期値にしています。",
))
retire_age = st.sidebar.slider(
    "リタイア年齢", min_value=40, max_value=75,
    value=config.DEFAULT_RETIRE_AGE, step=1, format="%d 歳",
)
pension_start_age = st.sidebar.slider(
    "年金受給開始年齢", min_value=60, max_value=75,
    value=config.DEFAULT_PENSION_START_AGE, step=1, format="%d 歳",
    help="リタイア〜受給開始までの「年金空白期間」は取り崩しになります。",
)

st.sidebar.subheader("📈 運用利回り")
rate_before = st.sidebar.slider(
    "リタイア前の運用利回り", min_value=0.0, max_value=10.0,
    value=config.DEFAULT_RATE_BEFORE * 100, step=0.5, format="%.1f%%",
) / 100.0
rate_after = st.sidebar.slider(
    "リタイア後の運用利回り", min_value=0.0, max_value=10.0,
    value=config.DEFAULT_RATE_AFTER * 100, step=0.5, format="%.1f%%",
) / 100.0

st.sidebar.subheader("💴 収入")
annual_income = float(st.sidebar.number_input(
    "現役時代の年間手取り収入", min_value=0,
    value=config.DEFAULT_ANNUAL_INCOME, step=100_000,
))
pension_monthly = float(st.sidebar.number_input(
    "年金（月額・受給開始後）", min_value=0,
    value=config.DEFAULT_PENSION_MONTHLY, step=10_000,
))
c_sev1, c_sev2 = st.sidebar.columns(2)
severance_age = int(c_sev1.number_input(
    "退職金 受取年齢", min_value=40, max_value=75,
    value=config.DEFAULT_SEVERANCE_AGE, step=1,
))
severance_amount = float(c_sev2.number_input(
    "退職金額", min_value=0,
    value=config.DEFAULT_SEVERANCE_AMOUNT, step=100_000,
))

st.sidebar.subheader("🏠 住居費（住宅ローン）")
housing_current = float(st.sidebar.number_input(
    "現在の月々支払額", min_value=0,
    value=config.DEFAULT_HOUSING_CURRENT_MONTHLY, step=1_000,
))
housing_revised = float(st.sidebar.number_input(
    "金利見直し後の月々支払額", min_value=0,
    value=config.DEFAULT_HOUSING_REVISED_MONTHLY, step=1_000,
))
housing_revise_age = int(st.sidebar.number_input(
    "金利見直しが適用される年齢", min_value=current_age, max_value=100,
    value=max(config.DEFAULT_HOUSING_REVISE_AGE, current_age), step=1,
))
housing_end_age = int(st.sidebar.number_input(
    "ローン支払い終了年齢", min_value=current_age, max_value=100,
    value=max(config.DEFAULT_HOUSING_END_AGE, current_age), step=1,
    help="この年齢以降は住居費0円。",
))

st.sidebar.subheader("🍚 基本生活費")
st.sidebar.caption("夫婦の食費・光熱費等のベース。子どもの養育費は年齢に応じ自動加算されます。")
default_living = int(settings.get("平均生活費（月額）", config.DEFAULT_LIVING_COST_MONTHLY))
base_living = float(st.sidebar.slider(
    "基本生活費（月額・現役）", min_value=100_000, max_value=800_000,
    value=default_living, step=10_000, format="¥%d",
))
retire_living = float(st.sidebar.slider(
    "基本生活費（月額・リタイア後）", min_value=50_000, max_value=800_000,
    value=config.DEFAULT_RETIRE_LIVING_COST_MONTHLY, step=10_000, format="¥%d",
))

st.sidebar.subheader("🎓 子どもの教育費")
children: list[lifeplan.Child] = []
for name in config.CHILDREN:
    with st.sidebar.expander(name, expanded=(name == config.CHILDREN[0])):
        birth = config.CHILD_BIRTHDATES[name]
        age = st.number_input(
            f"{name}の現在年齢", min_value=0, max_value=30,
            value=config.age_on(birth), step=1,
            key=f"age_{name}",
            help=f"生年月日 {birth:%Y-%m-%d} から自動計算しています。",
        )
        choices = {
            stage: st.selectbox(
                stage, config.SCHOOL_TYPES,
                index=config.SCHOOL_TYPES.index(config.DEFAULT_SCHOOL_CHOICE[stage]),
                key=f"{name}_{stage}",
            )
            for stage in config.EDUCATION_STAGES
        }
        children.append(lifeplan.Child(name=name, current_age=int(age), choices=choices))

st.sidebar.subheader("👨‍👩‍👧‍👦 多子世帯支援")
apply_child_allowance = st.sidebar.checkbox(
    "児童手当を反映（第3子以降は増額）", value=config.DEFAULT_APPLY_CHILD_ALLOWANCE,
    help="0〜18歳に支給。第3子以降は月3万円。",
)
apply_univ_free_multi = st.sidebar.checkbox(
    "多子世帯の大学無償化を適用", value=config.DEFAULT_APPLY_UNIV_FREE_MULTI,
    help=f"扶養する子が{config.MULTI_CHILD_THRESHOLD}人以上いる年は、大学生の授業料を免除扱いにします。",
)

st.sidebar.subheader("🎉 カスタム・ライフイベント")
st.sidebar.caption("車の買い替え・リフォーム等。「＋」で行を追加できます。")
default_events = pd.DataFrame({
    "ラベル": pd.Series([], dtype="string"),
    "年齢": pd.Series([], dtype="Int64"),
    "区分": pd.Series([], dtype="string"),
    "金額": pd.Series([], dtype="Int64"),
})
edited_events = st.sidebar.data_editor(
    default_events,
    num_rows="dynamic",
    width="stretch",
    key="custom_events",
    column_config={
        "ラベル": st.column_config.TextColumn("ラベル"),
        "年齢": st.column_config.NumberColumn("年齢", min_value=0, max_value=120, step=1),
        "区分": st.column_config.SelectboxColumn("区分", options=["支出", "収入"]),
        "金額": st.column_config.NumberColumn("金額", min_value=0, step=100_000, format="¥%d"),
    },
)
custom_events: list[dict] = []
for _, r in edited_events.iterrows():
    if pd.isna(r.get("年齢")) or pd.isna(r.get("金額")):
        continue
    kind = r.get("区分") if r.get("区分") in ("支出", "収入") else "支出"
    custom_events.append({
        "label": str(r.get("ラベル") or "イベント"),
        "age": int(r["年齢"]),
        "kind": kind,
        "amount": float(r["金額"]),
    })


# ===========================================================================
#  シミュレーション実行
# ===========================================================================
params = lifeplan.PlanParams(
    start_asset=start_asset,
    start_year=start_year,
    current_age=current_age,
    retire_age=int(retire_age),
    pension_start_age=int(pension_start_age),
    annual_income=annual_income,
    pension_monthly=pension_monthly,
    severance_age=severance_age,
    severance_amount=severance_amount,
    rate_before=rate_before,
    rate_after=rate_after,
    base_living_monthly=base_living,
    retire_living_monthly=retire_living,
    housing_current_monthly=housing_current,
    housing_revised_monthly=housing_revised,
    housing_revise_age=housing_revise_age,
    housing_end_age=housing_end_age,
    apply_child_allowance=apply_child_allowance,
    apply_univ_free_multi=apply_univ_free_multi,
    children=children,
    settings=settings,
    custom_events=custom_events,
)
sim = lifeplan.simulate(params)
events = lifeplan.milestones(params)


# ===========================================================================
#  メイングラフ: 資産推移（折れ線）＋ 年間収支（積み上げ棒＋収入線）
# ===========================================================================
st.subheader("資産推移と年間収支")

fig = make_subplots(specs=[[{"secondary_y": True}]])

# 年間支出（カテゴリ別の積み上げ棒: 第1軸）
for cat, color in EXPENSE_COLORS.items():
    fig.add_trace(
        go.Bar(x=sim["西暦"], y=sim[cat], name=cat, marker_color=color, opacity=0.85),
        secondary_y=False,
    )

# 年間収入（折れ線: 第1軸）
fig.add_trace(
    go.Scatter(
        x=sim["西暦"], y=sim["年間収入"], name="年間収入",
        mode="lines", line=dict(color=COLOR_INCOME, width=2, dash="dot"),
    ),
    secondary_y=False,
)

# 総資産推移（折れ線: 第2軸）
fig.add_trace(
    go.Scatter(
        x=sim["西暦"], y=sim["期末資産残高"], name="年末資産残高",
        mode="lines", line=dict(color=COLOR_ASSET, width=3.5),
    ),
    secondary_y=True,
)

# マイルストーン（縦の点線＋ラベル）
year_min, year_max = int(sim["西暦"].min()), int(sim["西暦"].max())
for ev in events:
    if not (year_min <= ev["year"] <= year_max):
        continue
    fig.add_vline(x=ev["year"], line=dict(color=COLOR_MILESTONE, width=1, dash="dot"))
    fig.add_annotation(
        x=ev["year"], y=1.0, yref="paper", text=ev["label"],
        showarrow=False, textangle=-90, xanchor="left",
        font=dict(size=10, color=COLOR_MILESTONE),
    )

fig.update_layout(
    barmode="stack", height=520, margin=dict(l=10, r=10, t=40, b=80),
    template="plotly_white", hovermode="x unified",
    # 凡例（7項目）は下部に横並び。スマホでも折り返して収まる
    legend=dict(orientation="h", yanchor="top", y=-0.15, x=0),
)
fig.update_xaxes(title_text="西暦")
fig.update_yaxes(title_text="年間収支（円）", secondary_y=False)
fig.update_yaxes(title_text="資産残高（円）", secondary_y=True)
fig.add_hline(y=0, line=dict(color="#c0392b", width=1), secondary_y=True)

st.plotly_chart(fig, width="stretch", key="lifeplan_main")
st.caption(
    "積み上げ棒＝その年の支出内訳、緑の点線＝年間収入、青の実線＝年末資産残高。"
    "縦の紫点線は主要ライフイベントです。"
)

st.divider()


# ===========================================================================
#  キャッシュフロー詳細表（折りたたみ）
# ===========================================================================
with st.expander("📋 キャッシュフロー詳細表", expanded=False):
    cols = [
        "西暦", "年齢", "給与", "年金", "児童手当", "退職金", "カスタム収入",
        "運用益", "基本生活費", "住居費", "養育費", "教育費", "カスタム支出",
        "年間収入", "年間支出", "期末資産残高",
    ]
    view = sim[cols].copy()
    money_cols = [c for c in cols if c not in ("西暦", "年齢")]
    st.dataframe(
        view.style.format({c: "¥{:,.0f}" for c in money_cols}),
        width="stretch", hide_index=True, height=460,
    )
