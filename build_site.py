"""
Unified listening report: one HTML file with three tabs.

  Overview   — calendar, listening clock, volume, all-time charts, bump chart,
               cumulative artists, discovery
  Forgotten  — songs you loved and left behind
               score = days silent x sqrt(lifetime plays x best-month plays)
  Evergreen  — songs that never left
               score = months in rotation x coverage

Reads scrobbles.csv, writes index.html. Run: python build_site.py
"""

import html as ihtml
from datetime import date, timedelta

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.offline import get_plotlyjs
from plotly.subplots import make_subplots

CSV_FILE = "scrobbles.csv"
OUT_FILE = "dashboard.html"
LOCAL_TZ = "America/Toronto"

FORG_MIN_PLAYS = 15
EVER_MIN_PLAYS = 30
EVER_MIN_LIFESPAN = 365   # days
RECENT_DAYS = 90
TABLE_PREVIEW = 100
BAR_ROWS = 25

# songs hidden from the forgotten tab, e.g. removed from streaming
EXCLUDE = [
    ("forget it", "screwyounick"),
    ("remember when", "sam sun"),
]

# ----------------------------------------------------------------- style ----
FONT = dict(family="Inter, 'Segoe UI', system-ui, sans-serif", color="#c9d4e0", size=13)
GRID = "rgba(130, 150, 175, 0.10)"
WARM = [[0.00, "#3a2438"], [0.35, "#8a2f45"], [0.65, "#e0523c"],
        [0.85, "#ff8c42"], [1.00, "#ffd07b"]]
COOL = [[0.00, "#235763"], [0.35, "#177f6f"], [0.65, "#0cb995"],
        [0.85, "#4cc9f0"], [1.00, "#c9f7e8"]]
CAL_SCALE = [[0.00, "#232a33"], [0.12, "#3d2a3f"], [0.30, "#712f49"],
             [0.50, "#b03a44"], [0.70, "#e85540"], [0.85, "#ff8c42"],
             [1.00, "#ffd07b"]]
PALETTE = ["#ff5964", "#ff9f45", "#ffd166", "#06d6a0", "#4cc9f0",
           "#7b8cde", "#b388eb", "#f72585", "#90be6d", "#e0aaff"]
YEAR_COLORS = ["#712f49", "#a83745", "#d94a3d", "#f26b3d", "#ff9e4a", "#ffd07b"]


def esc(s, n=None):
    s = str(s)
    if n and len(s) > n:
        s = s[: n - 1] + "…"
    return ihtml.escape(s)


def top_row(df):
    """Top row of a possibly-empty frame, or None. The card filters below can
    legitimately match nothing on a short listening history — .iloc[0] would
    raise IndexError there."""
    return None if df.empty else df.iloc[0]


def fmt_span(days):
    if days < 60:
        return f"{days} d"
    if days < 730:
        return f"{round(days / 30.4)} mo"
    return f"{days / 365.25:.1f} y"


def base_layout(fig, height):
    fig.update_layout(
        height=height, paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=FONT, margin=dict(l=12, r=12, t=26, b=12), showlegend=False,
        hoverlabel=dict(bgcolor="#1c2330", bordercolor="#3a4552",
                        font=dict(color="#e6edf3", family=FONT["family"])),
    )
    fig.update_xaxes(showgrid=False, zeroline=False, linecolor="#2b3442")
    fig.update_yaxes(showgrid=True, gridcolor=GRID, zeroline=False, linecolor="#2b3442")
    return fig


def ranked_bar(b, scale, score_fmt, customdata, hover_tmpl, label_max=34):
    """Ranked horizontal bars (#1 on top) with the song label ABOVE each bar."""
    b = b.iloc[::-1].reset_index(drop=True)      # worst rank at the bottom
    n = len(b)
    vmin, vmax = b["score"].min(), b["score"].max()
    pos = (b["score"] - vmin) / max(1e-9, vmax - vmin)
    fig = go.Figure(go.Bar(
        y=list(range(n)), x=b["score"], orientation="h", width=0.5,
        marker=dict(color=b["score"], colorscale=scale, cmin=vmin, cmax=vmax),
        text=[score_fmt(s) for s in b["score"]], textposition="inside",
        insidetextanchor="end",
        textfont=dict(size=11, color=["#20293a" if p > 0.55 else "#e6edf3"
                                      for p in pos]),
        customdata=customdata, hovertemplate=hover_tmpl,
    ))
    for i, (_, r) in enumerate(b.iterrows()):
        fig.add_annotation(
            x=0, y=i + 0.30, xanchor="left", yanchor="bottom", showarrow=False,
            text=f"<b>{esc(r['track'], label_max)}</b> · {esc(r['artist'], 26)}",
            font=dict(size=12, color="#e6edf3"),
        )
    base_layout(fig, 34 * n + 76)
    fig.update_xaxes(showticklabels=False, range=[0, vmax * 1.02])
    fig.update_yaxes(showticklabels=False, showgrid=False,
                     range=[-0.6, n - 1 + 0.78])
    return fig


def sparkline(vals, full_q):
    vmax = max(int(vals.max()), 1)
    bw, gap, h_max = 3, 1, 26
    rects = []
    for i, v in enumerate(vals):
        rel = (v / vmax) ** 0.5  # sqrt scale keeps quiet quarters visible
        h = 2 + (h_max - 2) * rel
        op = 0.22 + 0.78 * rel
        q = full_q[i]
        rects.append(
            f"<rect x='{i * (bw + gap)}' y='{h_max - h:.1f}' width='{bw}' "
            f"height='{h:.1f}' fill='#ff8c42' opacity='{op:.2f}'>"
            f"<title>{q.year} Q{q.quarter}: {v} plays</title></rect>")
    return (f"<svg class='spark' width='{len(vals) * (bw + gap)}' height='{h_max}'>"
            + "".join(rects) + "</svg>")


# ------------------------------------------------------------------ data ----
print("Loading data...")
df = pd.read_csv(CSV_FILE, usecols=["uts", "artist", "album", "track"])
df["artist"] = df["artist"].fillna("Unknown Artist")
df["track"] = df["track"].fillna("Unknown Track")
df["album"] = df["album"].fillna("")
df["dt"] = (pd.to_datetime(df["uts"], unit="s", utc=True)
              .dt.tz_convert(LOCAL_TZ).dt.tz_localize(None))
df["date"] = df["dt"].dt.date
df["hour"] = df["dt"].dt.hour
df["month"] = df["dt"].dt.to_period("M")
df["quarter"] = df["dt"].dt.to_period("Q")

total = len(df)
data_start, data_end = df["date"].min(), df["date"].max()
span_days = (data_end - data_start).days + 1
n_artists = df["artist"].nunique()
n_albums = df.loc[df["album"] != "", "album"].nunique()
n_tracks = df["track"].nunique()
ref = df["dt"].max()
ref_month = ref.to_period("M")
print(f"{total:,} scrobbles | {data_start} -> {data_end} | {n_artists:,} artists")

# ============================================================ OVERVIEW ====
print("Building overview tab...")
counts_by_date = df.groupby("date").size()
days_with = len(counts_by_date)
big_day, big_day_n = counts_by_date.idxmax(), int(counts_by_date.max())
days_arr = np.array(sorted(counts_by_date.index), dtype="datetime64[D]")
breaks = np.where(np.diff(days_arr).astype(int) != 1)[0] + 1
runs = np.split(days_arr, breaks)
longest = max(runs, key=len)
streak_n = len(longest)
streak_a, streak_b = pd.Timestamp(longest[0]).date(), pd.Timestamp(longest[-1]).date()
vc_art = df["artist"].value_counts()
top_artist, top_artist_n = vc_art.index[0], int(vc_art.iloc[0])
vc_trk = df.groupby(["track", "artist"]).size().sort_values(ascending=False)
(top_track, top_track_artist), top_track_n = vc_trk.index[0], int(vc_trk.iloc[0])
peak_hour = int(df["hour"].value_counts().idxmax())
night_pct = 100 * (df["hour"] < 6).mean()
avg_day = total / span_days

ov_cards = [
    (f"{total:,}", "Total scrobbles", f"{data_start:%b %d, %Y} → {data_end:%b %d, %Y}"),
    (f"{n_artists:,}", "Unique artists", f"{n_albums:,} albums · {n_tracks:,} tracks"),
    (f"{days_with:,}", "Days with music", f"of {span_days:,} days ({100*days_with/span_days:.0f}%)"),
    (f"{avg_day:.0f}", "Scrobbles per day", f"peak hour: {peak_hour:02d}:00 local"),
    (f"{streak_n}", "Longest streak (days)", f"{streak_a:%b %d} → {streak_b:%b %d, %Y}"),
    (f"{big_day_n:,}", "Biggest day", f"{big_day:%b %d, %Y}"),
    (esc(top_artist, 26), "Top artist", f"{top_artist_n:,} scrobbles"),
    (esc(top_track, 26), "Top track", f"{top_track_n:,} plays · {esc(top_track_artist, 22)}"),
    (f"{peak_hour:02d}:00", "Peak listening hour", "Eastern Time"),
    (f"{night_pct:.0f}%", "Night owl score", "scrobbles between midnight and 6am"),
]

# --- calendar -------------------------------------------------------------
years = sorted(df["dt"].dt.year.unique())
zmax_cal = max(2.0, float(np.percentile(counts_by_date.values, 97)))
fig_cal = make_subplots(rows=len(years), cols=1, shared_xaxes=True,
                        vertical_spacing=0.055)
max_cols = 0
for i, y in enumerate(years, start=1):
    first, last = date(y, 1, 1), date(y, 12, 31)
    first_mon = first - timedelta(days=first.weekday())
    ncols = ((last - first_mon).days) // 7 + 1
    max_cols = max(max_cols, ncols)
    z = np.full((7, ncols), np.nan)
    txt = np.full((7, ncols), "", dtype=object)
    d = first
    while d <= last:
        c = (d - first_mon).days // 7
        r = d.weekday()
        if data_start <= d <= data_end:
            v = int(counts_by_date.get(d, 0))
            z[r, c] = v
            txt[r, c] = (f"{d:%a, %b} {d.day}, {d:%Y}<br>{v:,} scrobbles"
                         if v else f"{d:%a, %b} {d.day}, {d:%Y}<br>No scrobbles")
        d += timedelta(days=1)
    fig_cal.add_trace(
        go.Heatmap(z=z, text=txt, hoverinfo="text",
                   colorscale=CAL_SCALE, zmin=0, zmax=zmax_cal,
                   xgap=2, ygap=2, showscale=(i == 1),
                   colorbar=dict(thickness=9, len=0.32, y=0.86, outlinewidth=0,
                                 tickfont=dict(size=10, color="#8b98a8"))),
        row=i, col=1)
    ax = "" if i == 1 else str(i)
    for m in range(1, 13):
        dm = date(y, m, 1)
        fig_cal.add_annotation(
            x=(dm - first_mon).days // 7, y=1.10, xref=f"x{ax}", yref=f"y{ax} domain",
            text=dm.strftime("%b"), showarrow=False,
            font=dict(size=9.5, color="#6d7a89"), xanchor="left")
for i, y in enumerate(years, start=1):
    fig_cal.update_yaxes(row=i, col=1, title_text=str(y),
                         title_font=dict(size=13, color="#8b98a8"))
fig_cal.update_yaxes(autorange="reversed", showgrid=False, zeroline=False,
                     tickvals=[0, 2, 4, 6], ticktext=["Mon", "Wed", "Fri", "Sun"],
                     tickfont=dict(size=9.5, color="#6d7a89"))
fig_cal.update_xaxes(showgrid=False, zeroline=False, showticklabels=False,
                     range=[-0.5, max_cols - 0.5])
base_layout(fig_cal, 132 * len(years) + 70)
fig_cal.update_layout(margin=dict(l=64, r=12, t=26, b=12))

# --- clock ----------------------------------------------------------------
days_order = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
              "Saturday", "Sunday"]
heat = (df.groupby([df["dt"].dt.day_name(), "hour"]).size()
          .unstack(fill_value=0)
          .reindex(index=days_order, columns=range(24), fill_value=0))
fig_clock = go.Figure(go.Heatmap(
    z=heat.values[::-1], x=list(range(24)), y=days_order[::-1],
    colorscale=CAL_SCALE, xgap=3, ygap=3,
    hovertemplate="%{y}, %{x}:00 – %{z:,} scrobbles<extra></extra>",
    colorbar=dict(thickness=9, outlinewidth=0,
                  tickfont=dict(size=10, color="#8b98a8"))))
base_layout(fig_clock, 330)
fig_clock.update_xaxes(tickmode="array", tickvals=list(range(0, 24, 2)),
                       ticktext=[f"{h:02d}" for h in range(0, 24, 2)],
                       tickfont=dict(size=9.5, color="#6d7a89"))
fig_clock.update_yaxes(showgrid=False, tickfont=dict(size=11))

# --- monthly volume --------------------------------------------------------
monthly = df.groupby("month").size()
monthly.index = monthly.index.to_timestamp()
roll = monthly.rolling(3, min_periods=1).mean()
bar_colors = [YEAR_COLORS[min(years.index(t.year), len(YEAR_COLORS) - 1)]
              for t in monthly.index]
fig_vol = go.Figure()
fig_vol.add_bar(x=monthly.index, y=monthly.values, marker_color=bar_colors,
                hovertemplate="%{x|%b %Y} – %{y:,} scrobbles<extra></extra>")
fig_vol.add_scatter(x=monthly.index, y=roll.values, mode="lines",
                    line=dict(color="#e6edf3", width=2),
                    hovertemplate="3-month avg: %{y:,.0f}<extra></extra>")
base_layout(fig_vol, 330)
fig_vol.update_xaxes(tickformat="%b\n%Y", tickfont=dict(size=10.5, color="#8b98a8"))
fig_vol.update_layout(bargap=0.25)

# --- all-time top charts ----------------------------------------------------
top_a = vc_art.head(15)
top_t = vc_trk.head(15)
top_al = (df.loc[df["album"] != ""].groupby(["album", "artist"]).size()
            .sort_values(ascending=False).head(15))
fig_top = make_subplots(rows=1, cols=3, horizontal_spacing=0.10,
                        subplot_titles=("Top Artists", "Top Tracks", "Top Albums"))
for col, (series, names) in enumerate([
    (top_a, [esc(x, 28) for x in top_a.index]),
    (top_t, [f"{esc(t, 24)}<br>{esc(a, 24)}" for t, a in top_t.index]),
    (top_al, [f"{esc(t, 24)}<br>{esc(a, 24)}" for t, a in top_al.index]),
], start=1):
    vals = series.values.astype(float)
    vmin, vmax = vals.min(), vals.max()
    pos = (vals - vmin) / max(1.0, vmax - vmin)
    txt_colors = ["#20293a" if p > 0.55 else "#e6edf3" for p in pos]
    fig_top.add_bar(
        y=names[::-1], x=vals[::-1], orientation="h",
        marker=dict(color=vals[::-1], colorscale=WARM, cmin=vmin, cmax=vmax),
        text=[f"{v:,.0f}" for v in vals[::-1]], textposition="inside",
        insidetextanchor="end", textfont=dict(size=10.5, color=txt_colors[::-1]),
        hovertemplate="%{y} – %{x:,.0f} scrobbles<extra></extra>",
        row=1, col=col)
    fig_top.update_xaxes(row=1, col=col, showgrid=False, showticklabels=False,
                         range=[0, vmax * 1.02])
    fig_top.update_yaxes(row=1, col=col, automargin=True, showgrid=False,
                         tickfont=dict(size=10))
base_layout(fig_top, 500)
fig_top.update_layout(margin=dict(l=12, r=30, t=40, b=12))

# --- bump chart -------------------------------------------------------------
top10 = vc_art.head(10).index.tolist()
q_counts = (df[df["artist"].isin(top10)]
            .groupby(["quarter", "artist"]).size().unstack(fill_value=0)
            .reindex(columns=top10, fill_value=0))
full_q = pd.period_range(df["quarter"].min(), df["quarter"].max(), freq="Q")
q_counts = q_counts.reindex(full_q, fill_value=0)
ranks = q_counts.rank(ascending=False, method="first", axis=1).astype(int)
nq = len(full_q)
q_labels = [f"{q.year} Q{q.quarter}" for q in full_q]
fig_bump = go.Figure()
for j, artist in enumerate(top10):
    txt = [f"{artist}<br>{q_labels[k]} – rank #{ranks.iloc[k, j]}"
           f" ({q_counts.iloc[k, j]:,} scrobbles)" for k in range(nq)]
    fig_bump.add_scatter(
        x=np.arange(nq), y=ranks[artist].values, mode="lines+markers",
        line=dict(color=PALETTE[j % len(PALETTE)], width=2.5),
        marker=dict(size=7), hoverinfo="text", text=txt)
    fig_bump.add_annotation(
        x=nq - 1 + 0.35, y=ranks[artist].iloc[-1], text=esc(artist, 18),
        showarrow=False, xanchor="left",
        font=dict(size=11, color=PALETTE[j % len(PALETTE)]))
tick_q1 = [k for k, q in enumerate(full_q) if q.quarter == 1]
base_layout(fig_bump, 420)
fig_bump.update_xaxes(tickmode="array", tickvals=tick_q1,
                      ticktext=[str(full_q[k].year) for k in tick_q1],
                      range=[-0.6, nq + 3.2], tickfont=dict(size=11, color="#8b98a8"))
fig_bump.update_yaxes(autorange="reversed", dtick=1, range=[10.6, 0.4],
                      tickvals=list(range(1, 11)), showgrid=True, gridcolor=GRID,
                      tickfont=dict(size=10.5, color="#8b98a8"))

# --- cumulative top artists -------------------------------------------------
top8 = vc_art.head(8).index.tolist()
full_m = pd.period_range(df["month"].min(), df["month"].max(), freq="M")
m_counts = (df[df["artist"].isin(top8)]
            .groupby(["month", "artist"]).size().unstack(fill_value=0)
            .reindex(index=full_m, columns=top8, fill_value=0))
m_cum = m_counts.cumsum()
mx = full_m.to_timestamp()
fig_cum = go.Figure()
for j, artist in enumerate(top8):
    fig_cum.add_scatter(x=mx, y=m_cum[artist].values, mode="lines",
                        line=dict(color=PALETTE[j % len(PALETTE)], width=2.5),
                        hovertemplate=f"{artist} – %{{y:,}} total<extra></extra>")
ends = sorted(((m_cum[a].iloc[-1], a, PALETTE[j % len(PALETTE)])
               for j, a in enumerate(top8)), reverse=True)
min_gap = m_cum.values.max() * 0.055
label_y, prev = [], None
for v, a, c in ends:
    y = v if prev is None else min(v, prev - min_gap)
    label_y.append(y)
    prev = y
for (v, a, c), y in zip(ends, label_y):
    fig_cum.add_annotation(x=mx[-1], y=y, text=f" {esc(a, 16)} ({v:,})",
                           showarrow=False, xanchor="left", xshift=6,
                           font=dict(size=11, color=c))
base_layout(fig_cum, 400)
fig_cum.update_xaxes(tickformat="%b\n%Y", tickfont=dict(size=10.5, color="#8b98a8"),
                     range=[mx[0], mx[-1]])
fig_cum.update_layout(margin=dict(l=12, r=150, t=26, b=12))

# --- discovery --------------------------------------------------------------
firsts = df.groupby("artist")["dt"].min()
new_pm = firsts.groupby(firsts.dt.to_period("M")).size().reindex(full_m, fill_value=0)
new_pm.index = new_pm.index.to_timestamp()
cum_unique = new_pm.cumsum()
fig_disc = make_subplots(specs=[[{"secondary_y": True}]])
fig_disc.add_bar(x=new_pm.index, y=new_pm.values, marker_color="#e85540",
                 opacity=0.85,
                 hovertemplate="%{x|%b %Y} – %{y} new artists<extra></extra>",
                 secondary_y=False)
fig_disc.add_scatter(x=new_pm.index, y=cum_unique.values, mode="lines",
                     line=dict(color="#4cc9f0", width=2.5),
                     hovertemplate="%{y:,} artists total<extra></extra>",
                     secondary_y=True)
base_layout(fig_disc, 340)
fig_disc.update_xaxes(tickformat="%b\n%Y", tickfont=dict(size=10.5, color="#8b98a8"))
fig_disc.update_yaxes(secondary_y=True, showgrid=False,
                      tickfont=dict(size=10.5, color="#4cc9f0"))
fig_disc.update_yaxes(secondary_y=False, tickfont=dict(size=10.5, color="#e85540"))
fig_disc.update_layout(bargap=0.25)

# ============================================================ FORGOTTEN ====
print("Building forgotten tab...")
songs = df.groupby(["track", "artist"]).agg(
    plays=("uts", "size"), last=("dt", "max"), first=("dt", "min")).reset_index()
songs["days_gone"] = (ref - songs["last"]).dt.days
songs["lifespan"] = (songs["last"] - songs["first"]).dt.days
songs["first_month"] = songs["first"].dt.to_period("M")
peak = (df.groupby(["track", "artist", "month"]).size()
          .rename("n").reset_index().sort_values("n", ascending=False)
          .drop_duplicates(["track", "artist"]).set_index(["track", "artist"]))
songs = songs.join(peak[["month", "n"]].rename(
    columns={"month": "peak_month", "n": "peak_plays"}), on=["track", "artist"])
songs["peak_plays"] = songs["peak_plays"].fillna(0).astype(int)
active = (df.groupby(["track", "artist"])["month"].nunique()
            .rename("active_months").reset_index())
songs = songs.merge(active, on=["track", "artist"])
songs["avail_months"] = songs["first_month"].apply(
    lambda m: (ref_month.year - m.year) * 12 + (ref_month.month - m.month) + 1)
songs["coverage"] = songs["active_months"] / songs["avail_months"]
songs["alive"] = (ref - songs["last"]).dt.days <= RECENT_DAYS

excluded = {(t.strip().lower(), a.strip().lower()) for t, a in EXCLUDE}
songs = songs[~songs.apply(
    lambda r: (r["track"].strip().lower(), r["artist"].strip().lower()) in excluded,
    axis=1)]

q_hist = (df.groupby(["track", "artist", "quarter"]).size()
            .unstack(fill_value=0).reindex(columns=full_q, fill_value=0))

# forgotten score: days silent x sqrt(plays x best-month plays)
forg = songs[songs["plays"] >= FORG_MIN_PLAYS].copy()
forg["score"] = forg["days_gone"] * (forg["plays"] * forg["peak_plays"]) ** 0.5
forg = forg.sort_values("score", ascending=False)
print(f"  {len(forg):,} forgotten candidates")
dust = forg[forg["days_gone"] >= 365]
f_top = top_row(forg)
f_big = top_row(dust.sort_values("plays", ascending=False))
f_cards = [
    (f"{len(dust):,}", "Songs gathering dust",
     f"≥{FORG_MIN_PLAYS} plays, unheard for 1+ year"),
    (f"{int(dust['plays'].sum()):,}", "Plays locked in them",
     "lifetime plays of those songs"),
    (esc(f_top["track"], 24), "Most forgotten",
     f"{f_top['plays']:,} plays · peak {f_top['peak_month'].strftime('%b %Y')}")
    if f_top is not None else
    ("—", "Most forgotten", f"no songs with ≥{FORG_MIN_PLAYS} plays"),
    (esc(f_big["track"], 24), "Biggest hit you've dropped",
     f"{f_big['plays']:,} plays · last {f_big['last']:%b %d, %Y}")
    if f_big is not None else
    ("—", "Biggest hit you've dropped", "nothing unheard for a full year yet"),
]

b = forg.head(BAR_ROWS)
fig_forg_bar = ranked_bar(
    b, WARM, lambda s: f"{s/1000:,.0f}k",
    list(zip(b["plays"], b["days_gone"], b["last"].dt.strftime("%b %d, %Y"),
             b["peak_month"].dt.strftime("%b %Y"), b["peak_plays"])),
    "%{y}<extra></extra>")  # hover replaced below via text-free approach
# richer hover: rebuild with name in text
fig_forg_bar.data[0].text = [f"{s/1000:,.0f}k" for s in b.iloc[::-1]["score"]]
fig_forg_bar.data[0].customdata = list(zip(
    [f"<b>{esc(t)}</b> · {esc(a)}" for t, a in zip(b.iloc[::-1]["track"],
                                                   b.iloc[::-1]["artist"])],
    b.iloc[::-1]["plays"], b.iloc[::-1]["days_gone"],
    b.iloc[::-1]["last"].dt.strftime("%b %d, %Y"),
    b.iloc[::-1]["peak_month"].dt.strftime("%b %Y"),
    b.iloc[::-1]["peak_plays"]))
fig_forg_bar.data[0].hovertemplate = (
    "%{customdata[0]}<br>forgotten score %{x:,.0f}"
    "<br>%{customdata[1]:,} plays · gone %{customdata[2]:,} days"
    "<br>last heard %{customdata[3]}"
    "<br>peak: %{customdata[4]} (%{customdata[5]} plays)<extra></extra>")

fig_forg_sc = go.Figure(go.Scatter(
    x=forg["plays"], y=forg["days_gone"], mode="markers",
    marker=dict(size=6.5, color=forg["score"], colorscale=WARM, opacity=0.75,
                cmin=forg["score"].min(), cmax=forg["score"].max(),
                colorbar=dict(title=dict(text="score", font=dict(size=11,
                                                                 color="#8b98a8")),
                              thickness=9, outlinewidth=0,
                              tickfont=dict(size=10, color="#8b98a8"))),
    text=[f"{esc(t)} · {esc(a)}" for t, a in zip(forg["track"], forg["artist"])],
    customdata=list(zip(forg["plays"], forg["days_gone"],
                        forg["last"].dt.strftime("%b %d, %Y"))),
    hovertemplate=("%{text}<br>%{customdata[0]:,} plays · gone "
                   "%{customdata[1]:,} days<br>last heard %{customdata[2]}"
                   "<extra></extra>")))
base_layout(fig_forg_sc, 430)
fig_forg_sc.update_xaxes(type="log", tickmode="array",
                         tickvals=[15, 25, 50, 100, 200, 500, 1000],
                         ticktext=["15", "25", "50", "100", "200", "500", "1000"],
                         title=dict(text="lifetime plays (log scale)",
                                    font=dict(size=11.5, color="#8b98a8")),
                         showgrid=True, gridcolor=GRID,
                         tickfont=dict(size=10.5, color="#8b98a8"))
fig_forg_sc.update_yaxes(title=dict(text="days since last play",
                                    font=dict(size=11.5, color="#8b98a8")),
                         tickfont=dict(size=10.5, color="#8b98a8"))

print("  building full forgotten table...")
# A history where nothing has been silent for long makes every forgotten score
# zero, and the bar width NaN. Same for an all-new evergreen list below.
f_max = forg["score"].max() or 1
f_rows = []
for i, (_, r) in enumerate(forg.iterrows(), start=1):
    rank_cls = "r1" if i == 1 else "r2" if i == 2 else "r3" if i == 3 else ""
    w = 4 + 96 * r["score"] / f_max
    key = ihtml.escape(f"{r['track']} {r['artist']}".lower(), quote=True)
    extra = " class='extra'" if i > TABLE_PREVIEW else ""
    f_rows.append(
        f"<tr{extra} data-s=\"{key}\"><td class='rank {rank_cls}'>{i}</td>"
        f"<td class='song'>{esc(r['track'], 40)}</td>"
        f"<td class='artist'>{esc(r['artist'], 26)}</td>"
        f"<td class='num-c'>{r['plays']:,}</td>"
        f"<td>{r['peak_month'].strftime('%b %Y')} "
        f"<span class='dim'>({int(r['peak_plays'])}×)</span></td>"
        f"<td>{r['last']:%b %d, %Y}</td>"
        f"<td>{r['days_gone']:,}</td>"
        f"<td class='dim'>{fmt_span(r['lifespan'])}</td>"
        f"<td>{sparkline(q_hist.loc[(r['track'], r['artist'])].values, full_q)}</td>"
        f"<td><div class='scorewrap'><div class='scorebar' style='width:{w:.0f}%'></div>"
        f"<span>{r['score']:,.0f}</span></div></td></tr>")
forg_table = (
    "<div class='tbl-controls'>"
    "<input id='q_forg' class='search' type='text' "
    "placeholder='Search title or artist…' autocomplete='off'>"
    "<span id='match_forg' class='matches'></span>"
    f"<button class='btn' id='btn_forg'></button></div>"
    f"<table id='ftable_forg' data-n='{len(forg):,}'><thead><tr>"
    "<th>#</th><th>Song</th><th>Artist</th><th>Plays</th><th>Peak month</th>"
    "<th>Last heard</th><th>Days gone</th>"
    "<th title='First play to last play'>Lifespan</th><th>History</th>"
    "<th style='width:20%' title='days silent × √(lifetime plays × best-month plays)'>"
    "Forgotten score</th></tr></thead>"
    f"<tbody>{''.join(f_rows)}</tbody></table>")

# ============================================================ EVERGREEN ====
print("Building evergreen tab...")
ever = songs[(songs["plays"] >= EVER_MIN_PLAYS)
             & (songs["lifespan"] >= EVER_MIN_LIFESPAN)].copy()
ever["score"] = ever["active_months"] * ever["coverage"]
ever = ever.sort_values(["score", "active_months"], ascending=False)
print(f"  {len(ever):,} evergreen candidates")
e_long = top_row(ever.sort_values("lifespan", ascending=False))
e_steady = top_row(ever[ever["lifespan"] >= 2 * 365].sort_values(
    ["coverage", "active_months"], ascending=False))
e_cards = [
    (f"{len(ever):,}", "Long-term relationships",
     f"≥{EVER_MIN_PLAYS} plays · in rotation 1+ year"),
    (f"{int(ever['alive'].sum()):,}", "Still in rotation",
     f"played in the last {RECENT_DAYS} days"),
    (esc(e_long["track"], 24), "Longest relationship",
     f"{fmt_span(e_long['lifespan'])} · {esc(e_long['artist'], 20)}")
    if e_long is not None else
    ("—", "Longest relationship", "no year-long song relationships yet"),
    (esc(e_steady["track"], 24), "Most reliable",
     f"played in {100 * e_steady['coverage']:.0f}% of {int(e_steady['avail_months'])} months")
    if e_steady is not None else
    ("—", "Most reliable", "needs a song with 2+ years of history"),
]

b = ever.head(BAR_ROWS)
fig_ever_bar = ranked_bar(b, COOL, lambda s: f"{s:.1f}", None, "")
fig_ever_bar.data[0].customdata = list(zip(
    [f"<b>{esc(t)}</b> · {esc(a)}" for t, a in zip(b.iloc[::-1]["track"],
                                                   b.iloc[::-1]["artist"])],
    b.iloc[::-1]["plays"], b.iloc[::-1]["active_months"],
    b.iloc[::-1]["avail_months"], b.iloc[::-1]["coverage"] * 100,
    b.iloc[::-1]["lifespan"], b.iloc[::-1]["last"].dt.strftime("%b %d, %Y")))
fig_ever_bar.data[0].hovertemplate = (
    "%{customdata[0]}<br>evergreen score %{x:.1f}"
    "<br>%{customdata[1]:,} plays · %{customdata[5]:,} days between first and last"
    "<br>played in %{customdata[2]} of %{customdata[3]} months (%{customdata[4]:.0f}%)"
    "<br>last heard %{customdata[6]}<extra></extra>")

fig_ever_sc = go.Figure(go.Scatter(
    x=ever["lifespan"] / 365.25, y=ever["coverage"] * 100, mode="markers",
    marker=dict(size=ever["plays"], sizemode="area",
                sizeref=2.0 * ever["plays"].max() / 26 ** 2, sizemin=4,
                color=ever["score"], colorscale=COOL, opacity=0.8,
                cmin=ever["score"].min(), cmax=ever["score"].max(),
                colorbar=dict(title=dict(text="score", font=dict(size=11,
                                                                 color="#8b98a8")),
                              thickness=9, outlinewidth=0,
                              tickfont=dict(size=10, color="#8b98a8"))),
    text=[f"{esc(t)} · {esc(a)}" for t, a in zip(ever["track"], ever["artist"])],
    customdata=list(zip(ever["plays"], ever["active_months"], ever["avail_months"],
                        ever["last"].dt.strftime("%b %d, %Y"))),
    hovertemplate=("%{text}<br>%{customdata[0]:,} plays · %{customdata[1]} of "
                   "%{customdata[2]} months<br>%{x:.1f} years between first and "
                   "last · %{y:.0f}% coverage<br>last heard %{customdata[3]}"
                   "<extra></extra>")))
base_layout(fig_ever_sc, 430)
fig_ever_sc.update_xaxes(title=dict(text="years between first and last play",
                                    font=dict(size=11.5, color="#8b98a8")),
                         showgrid=True, gridcolor=GRID,
                         tickfont=dict(size=10.5, color="#8b98a8"))
fig_ever_sc.update_yaxes(title=dict(text="% of months with a play",
                                    font=dict(size=11.5, color="#8b98a8")),
                         ticksuffix="%", range=[0, 102],
                         tickfont=dict(size=10.5, color="#8b98a8"))

print("  building full evergreen table...")
e_max = ever["score"].max() or 1
e_rows = []
for i, (_, r) in enumerate(ever.iterrows(), start=1):
    rank_cls = "r1" if i == 1 else "r2" if i == 2 else "r3" if i == 3 else ""
    w = 4 + 96 * r["score"] / e_max
    key = ihtml.escape(f"{r['track']} {r['artist']}".lower(), quote=True)
    dot = ("<span class='alive' title='played in the last "
           f"{RECENT_DAYS} days'></span>" if r["alive"] else "")
    extra = " class='extra'" if i > TABLE_PREVIEW else ""
    e_rows.append(
        f"<tr{extra} data-s=\"{key}\"><td class='rank {rank_cls}'>{i}</td>"
        f"<td class='song'>{dot}{esc(r['track'], 40)}</td>"
        f"<td class='artist'>{esc(r['artist'], 26)}</td>"
        f"<td class='num-c'>{r['plays']:,}</td>"
        f"<td>{r['first']:%b %d, %Y}</td>"
        f"<td>{r['last']:%b %d, %Y}</td>"
        f"<td class='dim'>{fmt_span(r['lifespan'])}</td>"
        f"<td>{int(r['active_months'])}<span class='dim'> / {int(r['avail_months'])}</span></td>"
        f"<td>{100 * r['coverage']:.0f}%</td>"
        f"<td>{sparkline(q_hist.loc[(r['track'], r['artist'])].values, full_q)}</td>"
        f"<td><div class='scorewrap'><div class='scorebar' style='width:{w:.0f}%'></div>"
        f"<span>{r['score']:.1f}</span></div></td></tr>")
ever_table = (
    "<div class='tbl-controls'>"
    "<input id='q_ever' class='search' type='text' "
    "placeholder='Search title or artist…' autocomplete='off'>"
    "<span id='match_ever' class='matches'></span>"
    f"<button class='btn' id='btn_ever'></button></div>"
    f"<table id='ftable_ever' data-n='{len(ever):,}'><thead><tr>"
    "<th>#</th><th>Song</th><th>Artist</th><th>Plays</th><th>First heard</th>"
    "<th>Last heard</th><th>Lifespan</th>"
    "<th title='Distinct months with a play / months since first play'>In rotation</th>"
    "<th title='Months with a play as % of months since first play'>Coverage</th>"
    "<th>History</th>"
    "<th style='width:16%' title='months in rotation × coverage'>Evergreen score</th>"
    "</tr></thead>"
    f"<tbody>{''.join(e_rows)}</tbody></table>")

# ============================================================ ASSEMBLY =====
print("Assembling index.html...")
plotly_js = get_plotlyjs()
cfg = dict(displaylogo=False, responsive=True)
figs = [fig_cal, fig_clock, fig_vol, fig_top, fig_bump, fig_cum, fig_disc,
        fig_forg_bar, fig_forg_sc, fig_ever_bar, fig_ever_sc]
fh = [f.to_html(full_html=False, include_plotlyjs=False, config=cfg) for f in figs]
(fh_cal, fh_clock, fh_vol, fh_top, fh_bump, fh_cum, fh_disc,
 fh_forg_bar, fh_forg_sc, fh_ever_bar, fh_ever_sc) = fh


def cards_html(cards):
    return "\n".join(
        f'<div class="card"><div class="num">{v}</div>'
        f'<div class="lbl">{l}</div><div class="sub2">{s}</div></div>'
        for v, l, s in cards)


def section(title, caption, inner):
    return (f'<section class="panel"><h2>{title}</h2>'
            f'<p class="cap">{caption}</p>{inner}</section>')


CSS = """
* { box-sizing: border-box; }
body { background:#0d1117; color:#e6edf3; margin:0; padding:0 20px 30px;
       font-family:'Inter','Segoe UI',system-ui,sans-serif; }
body[data-tab='overview']  { --a:#ff8c42; --b:#ff5964; --c:#ffd07b; }
body[data-tab='forgotten'] { --a:#ff8c42; --b:#e0523c; --c:#ffd07b; }
body[data-tab='evergreen'] { --a:#06d6a0; --b:#4cc9f0; --c:#b388eb; }
.wrap { max-width:1180px; margin:0 auto; }
nav.tabs { position:sticky; top:0; z-index:50; display:flex; align-items:flex-end;
           gap:4px; background:rgba(13,17,23,.93); backdrop-filter:blur(8px);
           border-bottom:1px solid #232b36; padding-top:12px; margin:0 -20px 0;
           padding-left:20px; padding-right:20px; }
.brand { font-weight:800; font-size:15px; margin-right:auto; padding:0 10px 11px;
         letter-spacing:-0.2px; }
.brand em { font-style:normal; color:var(--a); }
.tab { background:none; border:none; color:#8b98a8; font-family:inherit;
       font-size:13.5px; font-weight:600; padding:10px 14px 11px; cursor:pointer;
       border-bottom:2px solid transparent; }
.tab:hover { color:#e6edf3; }
.tab.active { color:var(--a); border-bottom-color:var(--a); }
.tabpage { display:none; }
.tabpage.active { display:block; }
h1 { font-size:42px; font-weight:800; margin:34px 0 0; letter-spacing:-0.5px;
     background:linear-gradient(90deg,var(--b),var(--a),var(--c));
     -webkit-background-clip:text; background-clip:text; color:transparent; }
.tag { color:#8b98a8; margin-top:10px; font-size:15px; }
a { color:var(--a); text-decoration:none; }
a:hover { text-decoration:underline; }
.cards { display:grid; grid-template-columns:repeat(auto-fit,minmax(200px,1fr));
         gap:14px; margin:36px 0 10px; }
.card { background:#161b22; border:1px solid #232b36; border-radius:14px;
        padding:18px 20px; transition:transform .15s ease, border-color .15s ease; }
.card:hover { transform:translateY(-2px); border-color:var(--a); }
.num { font-size:25px; font-weight:800; }
.lbl { color:#8b98a8; font-size:11.5px; text-transform:uppercase;
       letter-spacing:.09em; margin-top:5px; }
.sub2 { color:#5d6a78; font-size:12px; margin-top:7px; }
.panel { background:#161b22; border:1px solid #232b36; border-radius:14px;
         padding:24px 24px 12px; margin:24px 0; }
.panel h2 { margin:0 0 3px; font-size:19px; font-weight:700; }
.cap { color:#8b98a8; font-size:13px; margin:0 0 12px; }
.tbl-controls { display:flex; gap:10px; margin-bottom:12px; align-items:center; }
.search { flex:1; background:#0d1117; border:1px solid #2b3442; border-radius:10px;
          color:#e6edf3; font-family:inherit; font-size:14px; padding:10px 14px;
          outline:none; }
.search:focus { border-color:var(--a); }
.search::placeholder { color:#5d6a78; }
.matches { color:#5d6a78; font-size:12px; min-width:86px; text-align:right; }
.btn { background:#1c2330; border:1px solid #2b3442; color:#c9d4e0;
       border-radius:10px; padding:9px 14px; font-family:inherit; font-size:12px;
       font-weight:600; cursor:pointer; white-space:nowrap; }
.btn:hover { border-color:var(--a); color:#e6edf3; }
table { width:100%; border-collapse:collapse; font-size:12.5px; }
th { text-align:left; color:#8b98a8; text-transform:uppercase; font-size:10.5px;
     letter-spacing:.08em; padding:10px 10px; border-bottom:1px solid #2b3442; }
td { padding:7px 10px; border-bottom:1px solid #1c222b; color:#c9d4e0; }
tbody tr:hover td { background:#1a212b; }
tbody tr.extra { display:none; }
tbody tr.extra.revealed { display:table-row; }
.rank { color:#5d6a78; font-weight:600; }
.r1 { color:#ffd07b; } .r2 { color:#c9d4e0; } .r3 { color:#ff8c42; }
.song { font-weight:600; color:#e6edf3; }
.artist { color:#8b98a8; }
.num-c { font-variant-numeric:tabular-nums; }
.dim { color:#5d6a78; font-size:11.5px; }
.spark { display:block; }
.alive { display:inline-block; width:8px; height:8px; border-radius:50%;
         background:#06d6a0; margin-right:7px; }
.scorewrap { background:#1c222b; border-radius:5px; height:16px; position:relative;
             overflow:hidden; min-width:90px; }
.scorebar { background:linear-gradient(90deg,var(--b),var(--a)); height:100%;
            border-radius:5px; }
.scorewrap span { position:absolute; right:8px; top:0; font-size:11px;
                  line-height:16px; color:#e6edf3; font-variant-numeric:tabular-nums; }
footer { color:#5d6a78; font-size:12px; text-align:center; margin:44px 0 8px; }
"""

JS = """
function activate(name) {
  document.querySelectorAll('.tab').forEach(b =>
    b.classList.toggle('active', b.dataset.tab === name));
  document.querySelectorAll('.tabpage').forEach(p =>
    p.classList.toggle('active', p.id === 'tab-' + name));
  document.body.dataset.tab = name;
  document.querySelectorAll('#tab-' + name + ' .js-plotly-plot')
    .forEach(gd => Plotly.Plots.resize(gd));
  window.scrollTo({ top: 0 });
}
document.querySelectorAll('.tab').forEach(btn =>
  btn.addEventListener('click', () => {
    history.replaceState(null, '', '#' + btn.dataset.tab);
    activate(btn.dataset.tab);
  }));
const h = location.hash.slice(1);
activate(['overview', 'forgotten', 'evergreen'].includes(h) ? h : 'overview');

function wireTable(inputId, btnId, matchId, tableId) {
  const input = document.getElementById(inputId);
  const btn = document.getElementById(btnId);
  const match = document.getElementById(matchId);
  const table = document.getElementById(tableId);
  let showAll = false;
  function apply() {
    const s = input.value.toLowerCase();
    let n = 0;
    table.querySelectorAll('tbody tr').forEach(tr => {
      const ok = tr.dataset.s.includes(s) && (showAll || !tr.classList.contains('extra'));
      tr.classList.toggle('revealed', ok);
      if (ok) n++;
    });
    match.textContent = s ? n.toLocaleString() + ' found' : '';
    btn.textContent = showAll ? 'Show top ' + TABLE_PREVIEW
                              : 'Show all ' + table.dataset.n + ' songs';
  }
  var TABLE_PREVIEW = """ + str(TABLE_PREVIEW) + """;
  input.addEventListener('input', apply);
  btn.addEventListener('click', () => { showAll = !showAll; apply(); });
  apply();
}
wireTable('q_forg', 'btn_forg', 'match_forg', 'ftable_forg');
wireTable('q_ever', 'btn_ever', 'match_ever', 'ftable_ever');
"""

overview_tab = "\n".join([
    "<header><h1>Five years of you, in music</h1>",
    f"<p class='tag'>{total:,} scrobbles &nbsp;·&nbsp; {data_start:%b %Y} – {data_end:%b %Y}"
    f" &nbsp;·&nbsp; {n_artists:,} artists &nbsp;·&nbsp; times shown in Eastern Time</p></header>",
    f"<div class='cards'>{cards_html(ov_cards)}</div>",
    section("Every single day", "One cell per day of your listening life — brighter means more scrobbles.", fh_cal),
    section("When you press play", "Scrobbles by hour of day and day of week (local time).", fh_clock),
    section("The long run", "Monthly scrobbles with a 3-month rolling average.", fh_vol),
    section("The all-time charts", "Your 15 most scrobbled artists, tracks and albums.", fh_top),
    section("Your rotating obsessions", "Quarterly top-10 leaderboard — who was on top, and when.", fh_bump),
    section("How the leaderboard was built", "Cumulative scrobbles for your all-time top 8 artists.", fh_cum),
    section("Exploration vs. routine", "New artists discovered each month (bars) and total unique artists (line).", fh_disc),
])

forgotten_tab = "\n".join([
    "<header><h1>Forgotten songs</h1>",
    f"<p class='tag'>Tracks you loved and left behind — ranked by <b>days silent "
    f"&times; &radic;(lifetime plays &times; best-month plays)</b>, so short fierce "
    f"obsessions outrank slow burns &nbsp;·&nbsp; days counted from your latest "
    f"scrobble ({ref:%b %d, %Y})</p></header>",
    f"<div class='cards'>{cards_html(f_cards)}</div>",
    section("The top 25 most forgotten", f"Songs with at least {FORG_MIN_PLAYS} "
            "lifetime plays, ranked by forgotten score.", fh_forg_bar),
    section("Plays vs. time gone", "Every eligible song, plotted by how much you played "
            "it and how long it's been. The top-right corner is where nostalgia lives.",
            fh_forg_sc),
    section("The full list", f"All {len(forg):,} eligible songs — top {TABLE_PREVIEW} "
            "shown by default, search or hit “show all”. Hover the mini charts for "
            "quarterly plays.", forg_table),
])

evergreen_tab = "\n".join([
    "<header><h1>Evergreen songs</h1>",
    f"<p class='tag'>The ones that never left — ranked by <b>months in rotation "
    f"&times; coverage</b> (how many distinct months you played them, weighted by how "
    f"gaps-free that run was) &nbsp;·&nbsp; candidates: &ge;{EVER_MIN_PLAYS} plays, "
    f"lifespan &ge; 1 year</p></header>",
    f"<div class='cards'>{cards_html(e_cards)}</div>",
    section("The top 25 evergreen", "Long relationships with few gaps, ranked by "
            "evergreen score.", fh_ever_bar),
    section("Long & steady", "Every candidate by relationship length and consistency — "
            "bubble size is lifetime plays. Top-right is where the lifers live.",
            fh_ever_sc),
    section("The full list", f"All {len(ever):,} candidates — type to filter, hover "
            f"the mini charts for quarterly plays. <span class='alive'></span> = played "
            f"in the last {RECENT_DAYS} days.", ever_table),
])

page = "\n".join([
    "<!DOCTYPE html>",
    '<html><head><meta charset="utf-8">',
    '<meta name="viewport" content="width=device-width, initial-scale=1">',
    "<title>My listening</title>",
    '<link rel="preconnect" href="https://fonts.googleapis.com">',
    '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>',
    '<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800&display=swap" rel="stylesheet">',
    f"<style>{CSS}</style>",
    f"<script>{plotly_js}</script>",
    "</head><body data-tab='overview'><div class='wrap'>",
    "<nav class='tabs'><div class='brand'>♪ my <em>listening</em></div>",
    "<button class='tab active' data-tab='overview'>Overview</button>",
    "<button class='tab' data-tab='forgotten'>Forgotten songs</button>",
    "<button class='tab' data-tab='evergreen'>Evergreen songs</button></nav>",
    f"<main id='tab-overview' class='tabpage active'>{overview_tab}</main>",
    f"<main id='tab-forgotten' class='tabpage'>{forgotten_tab}</main>",
    f"<main id='tab-evergreen' class='tabpage'>{evergreen_tab}</main>",
    f"<footer>Built from {CSV_FILE} · {total:,} scrobbles · rendered locally with plotly</footer>",
    "</div>",
    f"<script>{JS}</script>",
    "</body></html>",
])

with open(OUT_FILE, "w", encoding="utf-8") as f:
    f.write(page)
print(f"Saved {OUT_FILE}")
