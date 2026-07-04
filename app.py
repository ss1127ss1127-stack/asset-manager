"""資産管理ダッシュボード（Streamlit）。

    streamlit run app.py

機能:
  - データ入力フォーム（マスタ参照のドロップダウン → データベースへ APPEND）
  - ダッシュボード（ポートフォリオ比較 / 総資産推移＋複利予測 / 安全資産vsリスク）

将来的に家族のライフプラン可視化へ拡張する前提で、
集計ロジックは analytics.py、Sheets I/O は gsheet.py に分離している。
"""

from __future__ import annotations

from datetime import datetime

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

import analytics
import config
import gsheet

# --- ページ設定 ------------------------------------------------------------
st.set_page_config(
    page_title="資産管理ダッシュボード",
    page_icon="💰",
    layout="wide",
    initial_sidebar_state="expanded",
)

# モダンな見た目のための軽いスタイル調整
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
        html { font-size: 15px; }               /* 文字を詰めて情報量を確保 */
        .block-container {
          padding-top: 1rem; padding-bottom: 1rem;
          padding-left: .6rem; padding-right: .6rem;
        }
        div[data-testid="stMetricValue"] { font-size: 1.4rem; }
        /* 2カラム表示を縦積みにして各要素の横幅を確保 */
        div[data-testid="stHorizontalBlock"] { flex-wrap: wrap; }
      }
    </style>
    """,
    unsafe_allow_html=True,
)

# 落ち着いた配色（安全＝青系、リスク＝オレンジ系）
COLOR_SAFE = "#2E86DE"
COLOR_RISK = "#E67E22"
COLOR_OTHER = "#95A5A6"
CLASS_COLORS = {"安全資産": COLOR_SAFE, "リスク資産": COLOR_RISK, "その他": COLOR_OTHER}
SEQ_COLORS = px.colors.qualitative.Set2


# --- データ取得（キャッシュ）----------------------------------------------
@st.cache_resource(show_spinner=False)
def get_client():
    return gsheet.get_client()


@st.cache_data(ttl=300, show_spinner="スプレッドシートを読み込み中…")
def load_data():
    client = get_client()
    df = gsheet.load_database(client)
    masters = gsheet.load_masters(client)
    return df, masters


def yen(value: float) -> str:
    return f"¥{value:,.0f}"


# --- サイドバー ------------------------------------------------------------
st.sidebar.title("💰 資産管理")
st.sidebar.caption("家族のライフプラン可視化に向けて")

if st.sidebar.button("🔄 データを再読み込み", width="stretch"):
    load_data.clear()
    st.rerun()

try:
    df, masters = load_data()
    data_ok = True
except Exception as e:  # noqa: BLE001
    detail = str(getattr(e, "__cause__", "") or e)
    data_ok = False
    df, masters = pd.DataFrame(columns=config.DATABASE_COLUMNS), {
        c: [] for c in config.MASTER_COLUMNS
    }
    st.sidebar.error("スプレッドシートに接続できませんでした。")

st.sidebar.divider()

# 複利シミュレーションの設定（サイドバー）
# 各ウィジェットに key を付与し、データ再読込（st.rerun）後も
# 表示と計算値がズレないように session_state で値を保持する。
st.sidebar.subheader("📈 複利シミュレーション設定")
annual_rate_pct = st.sidebar.slider(
    "想定年利", min_value=0.0, max_value=10.0,
    value=config.DEFAULT_ANNUAL_RATE * 100, step=0.5, format="%.1f%%",
    help="運用利回りの想定値（年率）。0.0%〜10.0% で設定できます。",
    key="sim_annual_rate_pct",
)
annual_rate = annual_rate_pct / 100.0
proj_years = st.sidebar.slider(
    "予測年数", min_value=5, max_value=30,
    value=config.DEFAULT_PROJECTION_YEARS, step=1, format="%d 年",
    key="sim_proj_years",
)

totals = analytics.monthly_total(df)
auto_contrib = analytics.average_monthly_increase(totals)
use_auto = st.sidebar.checkbox(
    "月平均増加額を自動算出", value=True,
    help=f"履歴から推定: 約 {yen(auto_contrib)}/月",
    key="sim_use_auto",
)
if use_auto:
    monthly_contrib = auto_contrib
    st.sidebar.caption(f"毎月の積立想定: **{yen(auto_contrib)}**（自動）")
else:
    monthly_contrib = float(
        st.sidebar.number_input(
            "毎月の積立額（手動）", min_value=0, value=int(max(auto_contrib, 0)),
            step=10000, key="sim_manual_contrib",
        )
    )


# --- 画面本体 --------------------------------------------------------------
st.title("資産管理ダッシュボード")

if not data_ok:
    st.error(
        "Google スプレッドシートに接続できませんでした。\n\n"
        f"**詳細**: {detail}"
    )
    if "has not been used" in detail or "disabled" in detail:
        st.warning(
            "**Google Sheets API が無効です。** プロジェクト所有者が以下を有効化してください:\n\n"
            "https://console.cloud.google.com/apis/library/sheets.googleapis.com?project=asset-app-500305"
        )
    else:
        st.warning(
            "スプレッドシートが共有されていない可能性があります。\n\n"
            "共有設定で次のサービスアカウントを「編集者」に追加してください:\n\n"
            "`asset-manager@asset-app-500305.iam.gserviceaccount.com`"
        )
    st.stop()

tab_dash, tab_input = st.tabs(["📊 ダッシュボード", "✏️ データ入力"])


# ===========================================================================
#  ダッシュボード
# ===========================================================================
def render_dashboard() -> None:
    if df.empty:
        st.info("まだデータがありません。「✏️ データ入力」タブから記録を追加してください。")
        return

    months = analytics.sorted_year_months(df)
    latest = months[-1]

    # 後続のグラフ・キャプションで使う集計値（サマリーカードは廃止）
    latest_total = float(totals.iloc[-1]["合計"]) if not totals.empty else 0.0
    sr = analytics.safe_risk_breakdown(df, latest)
    sr_total = sr.sum() if not sr.empty else 0.0

    # --- 上段: 総資産推移＋複利予測（左 2/3） / 安全 vs リスク（右 1/3）---
    left, right = st.columns([2, 1])

    with left:
        st.subheader("総資産推移と複利シミュレーション")
        proj = analytics.project_future(
            totals, annual_rate=annual_rate, years=proj_years,
            monthly_contribution=monthly_contrib,
        )
        fig = go.Figure()
        # 実績（実線）
        fig.add_trace(go.Scatter(
            x=totals["_date"], y=totals["合計"], mode="lines+markers",
            name="実績", line=dict(color=COLOR_SAFE, width=3),
        ))
        # 予測（点線）
        if not proj.empty:
            fig.add_trace(go.Scatter(
                x=proj["_date"], y=proj["予測額"], mode="lines",
                name=f"予測（年利{annual_rate*100:.1f}%・{proj_years}年）",
                line=dict(color=COLOR_RISK, width=2.5, dash="dot"),
            ))
            final_val = proj.iloc[-1]["予測額"]
            fig.add_annotation(
                x=proj.iloc[-1]["_date"], y=final_val,
                text=f"<b>{yen(final_val)}</b>", showarrow=True, arrowhead=2,
                ax=-40, ay=-40, font=dict(color=COLOR_RISK),
            )
        fig.update_layout(
            height=380, margin=dict(l=10, r=10, t=10, b=60),
            hovermode="x unified", template="plotly_white",
            # 凡例は下部（横並び）に配置。狭幅のスマホでもグラフ本体が潰れない
            legend=dict(orientation="h", yanchor="top", y=-0.18, x=0),
            yaxis_title="資産額（円）", xaxis_title=None,
        )
        st.plotly_chart(fig, width="stretch", key="trend_chart")
        if not proj.empty:
            st.caption(
                f"現在 {yen(latest_total)} を起点に、毎月 {yen(monthly_contrib)} を積み立てつつ"
                f"年利 {annual_rate*100:.1f}% で運用した場合、"
                f"{proj_years}年後は **{yen(proj.iloc[-1]['予測額'])}** の見込みです。"
            )

    with right:
        st.subheader("安全資産 vs リスク資産")
        st.caption(f"最新月（{latest}）の構成")
        if sr_total:
            sr_df = sr.reset_index()
            sr_df.columns = ["分類", "金額"]
            donut = px.pie(
                sr_df, names="分類", values="金額", hole=0.58,
                color="分類", color_discrete_map=CLASS_COLORS,
            )
            donut.update_traces(textinfo="percent", textposition="inside")
            donut.update_layout(
                height=300, margin=dict(l=0, r=0, t=0, b=0),
                showlegend=True,
                legend=dict(orientation="h", yanchor="bottom", y=-0.2, x=0),
                annotations=[dict(text=yen(sr_total), x=0.5, y=0.5,
                                  font=dict(size=15, color="#333"), showarrow=False)],
            )
            st.plotly_chart(donut, width="stretch", key="safe_risk_donut")
        else:
            st.info("分類できるデータがありません。")

    st.divider()

    # --- 下段: ポートフォリオ比較（2時点の円グラフ）---
    st.subheader("ポートフォリオ比較")
    st.caption("2つの年月を選んで、カテゴリ別の資産比率を見比べます。")

    c_sel_a, c_sel_b = st.columns(2)
    sel_a = c_sel_a.selectbox("比較① 年月", months, index=0)
    sel_b = c_sel_b.selectbox("比較② 年月", months, index=len(months) - 1)

    c_pie_a, c_pie_b = st.columns(2)
    # slot を key に含めることで、左右で同じ年月を選んでも ID が衝突しない
    for slot, (col, ym) in enumerate(((c_pie_a, sel_a), (c_pie_b, sel_b))):
        with col:
            series = analytics.portfolio_by_category(df, ym)
            total = series.sum()
            if total:
                pdf = series.reset_index()
                pdf.columns = ["カテゴリ", "金額"]
                pie = px.pie(
                    pdf, names="カテゴリ", values="金額", hole=0.0,
                    color_discrete_sequence=SEQ_COLORS,
                )
                pie.update_traces(textinfo="percent+label", textposition="inside")
                pie.update_layout(
                    height=340, margin=dict(l=0, r=0, t=30, b=0),
                    title=dict(text=f"{ym}　合計 {yen(total)}", x=0.5, font=dict(size=15)),
                    showlegend=False,
                )
                st.plotly_chart(pie, width="stretch", key=f"pf_pie_{slot}")
            else:
                st.info(f"{ym} のデータがありません。")

    st.divider()

    # --- 追加ビュー: 家族の資産を多角的に見る ---
    st.subheader("🔍 もっと見る")
    v_left, v_right = st.columns(2)

    with v_left:
        st.markdown("**👨‍👩‍👧‍👦 名義別の資産推移**")
        st.caption("家族の誰の資産がどう積み上がってきたか")
        owner_trend = analytics.owner_monthly_total(df)
        if not owner_trend.empty:
            area = px.area(
                owner_trend, x="_date", y="合計", color=config.COL_OWNER,
                color_discrete_sequence=px.colors.qualitative.Set2,
            )
            area.update_layout(
                height=360, margin=dict(l=10, r=10, t=10, b=60),
                template="plotly_white", hovermode="x unified",
                legend=dict(orientation="h", yanchor="top", y=-0.18, x=0,
                            title=None),
                yaxis_title="資産額（円）", xaxis_title=None,
            )
            st.plotly_chart(area, width="stretch", key="owner_area")
        else:
            st.info("データがありません。")

    with v_right:
        st.markdown("**🔆 資産の内訳サンバースト（最新月）**")
        st.caption("名義 → 口座名 → カテゴリ の階層で内訳を表示")
        latest_rows = df[
            (df[config.COL_YEAR_MONTH] == latest) & (df[config.COL_AMOUNT] > 0)
        ]
        if not latest_rows.empty:
            sb = px.sunburst(
                latest_rows,
                path=[config.COL_OWNER, config.COL_ACCOUNT, config.COL_CATEGORY],
                values=config.COL_AMOUNT,
                color=config.COL_OWNER,
                color_discrete_sequence=px.colors.qualitative.Set2,
            )
            sb.update_traces(textinfo="label+percent root")
            sb.update_layout(height=360, margin=dict(l=0, r=0, t=10, b=0))
            st.plotly_chart(sb, width="stretch", key="sunburst")
        else:
            st.info(f"{latest} のデータがありません。")


# ===========================================================================
#  データ入力フォーム
# ===========================================================================
def render_input() -> None:
    st.subheader("資産データの入力")
    st.caption("マスタの選択肢から選び、データベースシートに1行追記します。")

    owners = masters.get(config.COL_OWNER, [])
    accounts = masters.get(config.COL_ACCOUNT, [])
    categories = masters.get(config.COL_CATEGORY, [])

    if not (owners and accounts and categories):
        st.warning(
            "マスタの選択肢が読み込めていません。"
            "『マスタ』シートに 名義 / 口座名 / カテゴリ の列があるか確認してください。"
        )

    now = datetime.now()
    # clear_on_submit=False: 送信しても入力値を残す（毎月まとめ入力しやすい）
    with st.form("entry_form", clear_on_submit=False):
        c1, c2 = st.columns(2)
        year = c1.number_input("年", min_value=2000, max_value=2100,
                               value=now.year, step=1)
        month = c2.selectbox("月", list(range(1, 13)), index=now.month - 1,
                             format_func=lambda m: f"{m}月")

        owner = st.selectbox(config.COL_OWNER, owners) if owners else \
            st.text_input(config.COL_OWNER)
        account = st.selectbox(config.COL_ACCOUNT, accounts) if accounts else \
            st.text_input(config.COL_ACCOUNT)
        category = st.selectbox(config.COL_CATEGORY, categories) if categories else \
            st.text_input(config.COL_CATEGORY)

        amount = st.number_input("金額（円）", min_value=0, value=0, step=10000)
        note = st.text_input("備考（任意）", "")

        submitted = st.form_submit_button("📥 データベースに追加", type="primary",
                                          width="stretch")

    if submitted:
        ym = f"{int(year)}-{int(month):02d}"
        if amount <= 0:
            st.warning("金額を入力してください。")
            return
        try:
            gsheet.append_record(
                year_month=ym, owner=owner, account=account,
                category=category, amount=float(amount), note=note,
                client=get_client(),
            )
            load_data.clear()
            st.success(f"追加しました: {ym} / {owner} / {account} / {category} / {yen(amount)}")
            st.balloons()
        except Exception as e:  # noqa: BLE001
            st.error(f"追加に失敗しました: {e}")

    # 直近データのプレビュー
    if not df.empty:
        st.divider()
        st.caption("最近の記録（末尾10件）")
        st.dataframe(
            df.tail(10).iloc[::-1], width="stretch", hide_index=True
        )


with tab_dash:
    render_dashboard()

with tab_input:
    render_input()
