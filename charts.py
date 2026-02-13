#!/usr/bin/env python3
"""
fortune0 Chart Generator
=========================

Generates PNG chart images from platform data using matplotlib + numpy.
Called by server.py endpoints — returns raw PNG bytes.

Usage:
    from charts import generate_chart
    png_bytes = generate_chart("portfolio", domains_data, params)
"""

import io
import json
import os
import math
from datetime import datetime, timezone
from collections import defaultdict

try:
    import matplotlib
    matplotlib.use('Agg')  # Non-interactive backend (no GUI needed)
    import matplotlib.pyplot as plt
    import matplotlib.ticker as ticker
    import numpy as np
    HAS_MPL = True
except ImportError:
    HAS_MPL = False

# ═══════════════════════════════════════════
#  STYLE CONFIG
# ═══════════════════════════════════════════

# fortune0 brand colors
COLORS = {
    "bg": "#0a0a0a",
    "card": "#141414",
    "gold": "#d4a843",
    "green": "#00ffaa",
    "red": "#ff4444",
    "blue": "#4488ff",
    "purple": "#aa44ff",
    "orange": "#ff8844",
    "text": "#e0e0e0",
    "dim": "#666666",
    "grid": "#222222",
}

PALETTE = ["#d4a843", "#00ffaa", "#4488ff", "#ff8844", "#aa44ff", "#ff4444", "#44ffaa", "#ff44aa", "#44aaff", "#ffaa44"]


def _setup_style(fig, ax):
    """Apply fortune0 dark theme to a chart."""
    fig.patch.set_facecolor(COLORS["bg"])
    ax.set_facecolor(COLORS["card"])
    ax.tick_params(colors=COLORS["text"], labelsize=9)
    ax.xaxis.label.set_color(COLORS["text"])
    ax.yaxis.label.set_color(COLORS["text"])
    ax.title.set_color(COLORS["gold"])
    ax.title.set_fontsize(14)
    ax.title.set_fontweight("bold")
    for spine in ax.spines.values():
        spine.set_color(COLORS["grid"])
    ax.grid(True, alpha=0.15, color=COLORS["dim"])


def _to_png(fig, dpi=150):
    """Render figure to PNG bytes."""
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=dpi, bbox_inches="tight",
                facecolor=fig.get_facecolor(), edgecolor="none")
    plt.close(fig)
    buf.seek(0)
    return buf.read()


# ═══════════════════════════════════════════
#  CHART: Domain Portfolio Value Distribution
# ═══════════════════════════════════════════

def chart_portfolio(domains, params=None):
    """Bar chart of top domains by value."""
    params = params or {}
    top_n = int(params.get("top", 20))

    sorted_d = sorted(domains, key=lambda d: d.get("value", 0), reverse=True)[:top_n]
    names = [d["domain"].replace(".com", "").replace(".io", "").replace(".ai", "") for d in sorted_d]
    values = [d.get("value", 0) for d in sorted_d]

    fig, ax = plt.subplots(figsize=(12, 6))
    _setup_style(fig, ax)

    bars = ax.barh(range(len(names)), values, color=COLORS["gold"], alpha=0.85, edgecolor=COLORS["gold"], linewidth=0.5)
    ax.set_yticks(range(len(names)))
    ax.set_yticklabels(names, fontsize=8)
    ax.invert_yaxis()
    ax.set_xlabel("Domain Value Score")
    ax.set_title(f"Top {top_n} Domains by Value")

    # Value labels on bars
    for bar, val in zip(bars, values):
        ax.text(bar.get_width() + max(values) * 0.01, bar.get_y() + bar.get_height()/2,
                str(val), va="center", color=COLORS["text"], fontsize=8)

    # Total portfolio value
    total = sum(d.get("value", 0) for d in domains)
    ax.text(0.98, 0.02, f"Total Portfolio: {total:,} pts  |  {len(domains)} domains",
            transform=ax.transAxes, ha="right", va="bottom",
            color=COLORS["dim"], fontsize=9)

    return _to_png(fig)


# ═══════════════════════════════════════════
#  CHART: Value Distribution Histogram
# ═══════════════════════════════════════════

def chart_distribution(domains, params=None):
    """Histogram of domain value distribution."""
    values = [d.get("value", 0) for d in domains]

    fig, ax = plt.subplots(figsize=(10, 5))
    _setup_style(fig, ax)

    bins = np.logspace(0, np.log10(max(values) + 1), 25) if max(values) > 0 else 25
    ax.hist(values, bins=bins, color=COLORS["green"], alpha=0.7, edgecolor=COLORS["bg"])
    ax.set_xscale("log")
    ax.set_xlabel("Domain Value (log scale)")
    ax.set_ylabel("Count")
    ax.set_title("Domain Value Distribution")

    # Stats annotation
    avg = sum(values) / len(values) if values else 0
    median = sorted(values)[len(values)//2] if values else 0
    ax.text(0.98, 0.95, f"Mean: {avg:.0f}  |  Median: {median}  |  Total: {len(values)}",
            transform=ax.transAxes, ha="right", va="top",
            color=COLORS["dim"], fontsize=9)

    return _to_png(fig)


# ═══════════════════════════════════════════
#  CHART: Expiration Timeline
# ═══════════════════════════════════════════

def chart_expiry(domains, params=None):
    """Timeline showing when domains expire, grouped by month."""
    now = datetime.now(timezone.utc)
    month_counts = defaultdict(int)
    month_values = defaultdict(int)

    for d in domains:
        exp = d.get("expires", "")
        try:
            dt = datetime.strptime(exp, "%Y-%m-%d")
            key = dt.strftime("%Y-%m")
            month_counts[key] += 1
            month_values[key] += d.get("value", 0)
        except (ValueError, TypeError):
            continue

    months = sorted(month_counts.keys())
    counts = [month_counts[m] for m in months]
    values = [month_values[m] for m in months]

    fig, ax1 = plt.subplots(figsize=(12, 5))
    _setup_style(fig, ax1)

    x = range(len(months))
    bars = ax1.bar(x, counts, color=COLORS["gold"], alpha=0.7, label="Domains expiring")
    ax1.set_xticks(x)
    ax1.set_xticklabels([m[5:] + "\n" + m[:4] for m in months], fontsize=8, rotation=0)
    ax1.set_ylabel("Domains Expiring", color=COLORS["gold"])
    ax1.set_title("Domain Expiration Timeline")

    # Second y-axis for value at risk
    ax2 = ax1.twinx()
    ax2.plot(x, values, color=COLORS["red"], marker="o", markersize=4, linewidth=2, label="Value at risk")
    ax2.set_ylabel("Value at Risk", color=COLORS["red"])
    ax2.tick_params(colors=COLORS["text"])

    # Combined legend
    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labels1 + labels2, loc="upper left",
               facecolor=COLORS["card"], edgecolor=COLORS["grid"],
               labelcolor=COLORS["text"], fontsize=8)

    return _to_png(fig)


# ═══════════════════════════════════════════
#  CHART: Category Breakdown (word-based)
# ═══════════════════════════════════════════

def chart_categories(domains, params=None):
    """Pie chart grouping domains by detected category keywords."""
    import re

    categories = {
        "Privacy/Data": ["death", "data", "privacy", "delete", "vault", "proof", "essential"],
        "Real Estate": ["realtor", "home", "local", "service", "permit", "contractor", "coastal"],
        "Finance/Business": ["fortune", "dollar", "cash", "deal", "ipo", "sell", "bootstrap", "trillion", "agent"],
        "Education": ["lesson", "plan", "learn", "class", "course", "reflect", "teach", "skill"],
        "Memes/Culture": ["meme", "vibe", "cringe", "delulu", "oof", "yikes", "simp", "fart", "ghost"],
        "Creative/Brand": ["brand", "art", "mascot", "tattoo", "pfp", "design", "canvas"],
        "Social/Community": ["friend", "join", "heartfelt", "soul", "care", "talk", "share"],
        "Tech/Dev": ["repo", "api", "code", "chrome", "browser", "kernel", "template", "tool"],
    }

    cat_counts = defaultdict(int)
    cat_values = defaultdict(int)

    for d in domains:
        name = d["domain"].lower()
        matched = False
        for cat, keywords in categories.items():
            for kw in keywords:
                if kw in name:
                    cat_counts[cat] += 1
                    cat_values[cat] += d.get("value", 0)
                    matched = True
                    break
            if matched:
                break
        if not matched:
            cat_counts["Other"] += 1
            cat_values["Other"] += d.get("value", 0)

    labels = list(cat_counts.keys())
    sizes = [cat_counts[l] for l in labels]
    colors = PALETTE[:len(labels)]

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 6))
    fig.patch.set_facecolor(COLORS["bg"])

    # Pie chart — count
    ax1.set_facecolor(COLORS["bg"])
    wedges, texts, autotexts = ax1.pie(sizes, labels=labels, colors=colors, autopct="%1.0f%%",
                                        textprops={"color": COLORS["text"], "fontsize": 8},
                                        pctdistance=0.8, startangle=90)
    for t in autotexts:
        t.set_fontsize(7)
        t.set_color(COLORS["bg"])
    ax1.set_title("Domains by Category", color=COLORS["gold"], fontsize=13, fontweight="bold")

    # Bar chart — value by category
    ax2.set_facecolor(COLORS["card"])
    vals = [cat_values[l] for l in labels]
    bars = ax2.barh(labels, vals, color=colors, alpha=0.85)
    ax2.set_xlabel("Total Value", color=COLORS["text"])
    ax2.set_title("Value by Category", color=COLORS["gold"], fontsize=13, fontweight="bold")
    ax2.tick_params(colors=COLORS["text"], labelsize=9)
    for spine in ax2.spines.values():
        spine.set_color(COLORS["grid"])
    ax2.grid(True, alpha=0.15, color=COLORS["dim"], axis="x")

    fig.tight_layout(pad=2)
    return _to_png(fig)


# ═══════════════════════════════════════════
#  CHART: Custom Generator (numbers → image)
# ═══════════════════════════════════════════

def chart_generator(domains, params=None):
    """
    Custom chart from user-supplied data.
    params:
        labels: comma-separated labels
        values: comma-separated numbers
        chart_type: bar, line, pie, scatter (default: bar)
        title: chart title
        color: hex color override
    """
    params = params or {}
    labels_raw = params.get("labels", "A,B,C,D,E")
    values_raw = params.get("values", "10,25,15,30,20")
    chart_type = params.get("chart_type", "bar")
    title = params.get("title", "Custom Chart")
    color = params.get("color", COLORS["gold"])

    labels = [l.strip() for l in labels_raw.split(",")]
    try:
        values = [float(v.strip()) for v in values_raw.split(",")]
    except ValueError:
        values = [0] * len(labels)

    # Pad if mismatched
    while len(values) < len(labels):
        values.append(0)
    while len(labels) < len(values):
        labels.append(f"#{len(labels)+1}")

    fig, ax = plt.subplots(figsize=(10, 6))
    _setup_style(fig, ax)
    ax.set_title(title)

    x = range(len(labels))

    if chart_type == "line":
        ax.plot(x, values, color=color, marker="o", linewidth=2, markersize=6)
        ax.fill_between(x, values, alpha=0.15, color=color)
        ax.set_xticks(x)
        ax.set_xticklabels(labels, fontsize=9)

    elif chart_type == "pie":
        ax.set_facecolor(COLORS["bg"])
        colors_list = PALETTE[:len(labels)]
        ax.pie(values, labels=labels, colors=colors_list, autopct="%1.1f%%",
               textprops={"color": COLORS["text"], "fontsize": 9}, startangle=90)

    elif chart_type == "scatter":
        if len(values) >= 2:
            mid = len(values) // 2
            xs = values[:mid]
            ys = values[mid:mid+len(xs)]
            scatter_labels = labels[:len(xs)]
            ax.scatter(xs, ys, c=color, s=100, alpha=0.8, edgecolors=COLORS["text"], linewidth=0.5)
            for i, lbl in enumerate(scatter_labels):
                ax.annotate(lbl, (xs[i], ys[i]), textcoords="offset points",
                           xytext=(5, 5), color=COLORS["text"], fontsize=8)
            ax.set_xlabel("X Values")
            ax.set_ylabel("Y Values")
        else:
            ax.text(0.5, 0.5, "Need at least 4 values for scatter\n(first half = X, second half = Y)",
                    transform=ax.transAxes, ha="center", va="center", color=COLORS["dim"])

    else:  # bar (default)
        bars = ax.bar(x, values, color=color, alpha=0.85, edgecolor=color, linewidth=0.5)
        ax.set_xticks(x)
        ax.set_xticklabels(labels, fontsize=9)
        for bar, val in zip(bars, values):
            ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + max(values)*0.02,
                    f"{val:g}", ha="center", va="bottom", color=COLORS["text"], fontsize=8)

    return _to_png(fig)


# ═══════════════════════════════════════════
#  CHART: Platform Health Dashboard
# ═══════════════════════════════════════════

def chart_platform(domains, params=None):
    """
    Multi-panel platform overview.
    params should include platform stats from the database.
    """
    params = params or {}
    total_users = int(params.get("total_users", 0))
    active_users = int(params.get("active_users", 0))
    total_revenue = float(params.get("total_revenue", 0))
    total_credits = float(params.get("total_credits", 0))
    total_domains = len(domains)
    total_value = sum(d.get("value", 0) for d in domains)

    fig, axes = plt.subplots(2, 3, figsize=(15, 8))
    fig.patch.set_facecolor(COLORS["bg"])
    fig.suptitle("fortune0 Platform Dashboard", color=COLORS["gold"], fontsize=16, fontweight="bold", y=0.98)

    # Panel 1: User funnel
    ax = axes[0][0]
    ax.set_facecolor(COLORS["card"])
    labels = ["Total Users", "Active (Paid)"]
    vals = [total_users, active_users]
    bars = ax.bar(labels, vals, color=[COLORS["blue"], COLORS["green"]], alpha=0.8)
    ax.set_title("User Funnel", color=COLORS["text"], fontsize=11)
    ax.tick_params(colors=COLORS["text"])
    for spine in ax.spines.values():
        spine.set_color(COLORS["grid"])
    for bar, val in zip(bars, vals):
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.1,
                str(val), ha="center", color=COLORS["text"], fontsize=10)

    # Panel 2: Revenue
    ax = axes[0][1]
    ax.set_facecolor(COLORS["card"])
    rev_labels = ["Revenue", "Credits Issued"]
    rev_vals = [total_revenue, total_credits]
    bars = ax.bar(rev_labels, rev_vals, color=[COLORS["gold"], COLORS["purple"]], alpha=0.8)
    ax.set_title("Revenue & Credits", color=COLORS["text"], fontsize=11)
    ax.tick_params(colors=COLORS["text"])
    for spine in ax.spines.values():
        spine.set_color(COLORS["grid"])
    for bar, val in zip(bars, rev_vals):
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.1,
                f"${val:,.0f}" if "Rev" in rev_labels[bars.index(bar) if bar in bars else 0] else f"{val:,.0f}",
                ha="center", color=COLORS["text"], fontsize=10)

    # Panel 3: Domain portfolio summary
    ax = axes[0][2]
    ax.set_facecolor(COLORS["card"])
    dom_labels = ["Domains", "Total Value"]
    dom_vals = [total_domains, total_value]
    bars = ax.bar(dom_labels, dom_vals, color=[COLORS["orange"], COLORS["gold"]], alpha=0.8)
    ax.set_title("Domain Portfolio", color=COLORS["text"], fontsize=11)
    ax.tick_params(colors=COLORS["text"])
    for spine in ax.spines.values():
        spine.set_color(COLORS["grid"])
    for bar, val in zip(bars, dom_vals):
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + max(dom_vals)*0.02,
                f"{val:,}", ha="center", color=COLORS["text"], fontsize=10)

    # Panel 4: Top 10 domains (mini bar)
    ax = axes[1][0]
    _setup_style(fig, ax)  # Reuse for grid
    ax.set_facecolor(COLORS["card"])
    top10 = sorted(domains, key=lambda d: d.get("value", 0), reverse=True)[:10]
    t_names = [d["domain"].replace(".com", "")[:12] for d in top10]
    t_vals = [d.get("value", 0) for d in top10]
    ax.barh(range(len(t_names)), t_vals, color=COLORS["gold"], alpha=0.7)
    ax.set_yticks(range(len(t_names)))
    ax.set_yticklabels(t_names, fontsize=7)
    ax.invert_yaxis()
    ax.set_title("Top 10 Domains", color=COLORS["text"], fontsize=11)

    # Panel 5: Status breakdown
    ax = axes[1][1]
    ax.set_facecolor(COLORS["bg"])
    status_counts = {}
    for d in domains:
        s = d.get("status", "open")
        status_counts[s] = status_counts.get(s, 0) + 1
    if status_counts:
        s_labels = list(status_counts.keys())
        s_sizes = [status_counts[l] for l in s_labels]
        s_colors = [COLORS["green"] if l == "launched" else COLORS["gold"] for l in s_labels]
        ax.pie(s_sizes, labels=s_labels, colors=s_colors, autopct="%1.0f%%",
               textprops={"color": COLORS["text"], "fontsize": 9}, startangle=90)
    ax.set_title("Domain Status", color=COLORS["text"], fontsize=11)

    # Panel 6: Value tiers
    ax = axes[1][2]
    ax.set_facecolor(COLORS["card"])
    tiers = {"1000+": 0, "100-999": 0, "50-99": 0, "10-49": 0, "<10": 0}
    for d in domains:
        v = d.get("value", 0)
        if v >= 1000: tiers["1000+"] += 1
        elif v >= 100: tiers["100-999"] += 1
        elif v >= 50: tiers["50-99"] += 1
        elif v >= 10: tiers["10-49"] += 1
        else: tiers["<10"] += 1
    tier_labels = list(tiers.keys())
    tier_vals = [tiers[l] for l in tier_labels]
    bars = ax.bar(tier_labels, tier_vals, color=PALETTE[:len(tier_labels)], alpha=0.8)
    ax.set_title("Value Tiers", color=COLORS["text"], fontsize=11)
    ax.tick_params(colors=COLORS["text"])
    for spine in ax.spines.values():
        spine.set_color(COLORS["grid"])
    for bar, val in zip(bars, tier_vals):
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.2,
                str(val), ha="center", color=COLORS["text"], fontsize=9)

    fig.tight_layout(rect=[0, 0, 1, 0.95])
    return _to_png(fig)


# ═══════════════════════════════════════════
#  CHART: Network Map (domains as nodes)
# ═══════════════════════════════════════════

def chart_network(domains, params=None):
    """Scatter plot showing domains as sized nodes — value = size, position = category cluster."""
    import re

    categories = {
        "Privacy": ["death", "data", "privacy", "delete", "vault", "proof"],
        "Finance": ["fortune", "dollar", "cash", "deal", "ipo", "sell", "trillion"],
        "Education": ["lesson", "plan", "learn", "class", "course", "reflect", "skill"],
        "Memes": ["meme", "vibe", "cringe", "delulu", "oof", "yikes", "simp"],
        "Real Estate": ["realtor", "home", "local", "service", "permit", "contractor"],
        "Tech": ["repo", "api", "code", "chrome", "browser", "kernel", "template"],
    }

    # Assign each domain a category
    cat_positions = {}
    n_cats = len(categories)
    for i, cat in enumerate(categories.keys()):
        angle = 2 * math.pi * i / n_cats
        cat_positions[cat] = (math.cos(angle) * 3, math.sin(angle) * 3)
    cat_positions["Other"] = (0, 0)

    xs, ys, sizes, colors, labels = [], [], [], [], []
    np_rng = np.random.RandomState(42)

    for d in domains:
        name = d["domain"].lower()
        value = d.get("value", 0)
        cat = "Other"
        for c, keywords in categories.items():
            if any(kw in name for kw in keywords):
                cat = c
                break

        cx, cy = cat_positions[cat]
        # Jitter within cluster
        xs.append(cx + np_rng.normal(0, 0.6))
        ys.append(cy + np_rng.normal(0, 0.6))
        sizes.append(max(20, value * 0.15))
        cat_idx = list(categories.keys()).index(cat) if cat in categories else len(categories)
        colors.append(PALETTE[cat_idx % len(PALETTE)])
        labels.append(d["domain"].replace(".com", "")[:10])

    fig, ax = plt.subplots(figsize=(12, 10))
    _setup_style(fig, ax)
    ax.set_title("Domain Network Map")

    ax.scatter(xs, ys, s=sizes, c=colors, alpha=0.6, edgecolors=COLORS["text"], linewidth=0.3)

    # Label top domains
    top_indices = sorted(range(len(sizes)), key=lambda i: sizes[i], reverse=True)[:15]
    for i in top_indices:
        ax.annotate(labels[i], (xs[i], ys[i]),
                   textcoords="offset points", xytext=(5, 5),
                   color=COLORS["text"], fontsize=7, alpha=0.9)

    # Category labels
    for cat, (cx, cy) in cat_positions.items():
        if cat != "Other":
            ax.text(cx, cy + 1.5, cat, ha="center", va="center",
                   color=COLORS["gold"], fontsize=11, fontweight="bold", alpha=0.8)

    ax.set_xlim(-6, 6)
    ax.set_ylim(-6, 6)
    ax.set_aspect("equal")
    ax.axis("off")

    return _to_png(fig)


# ═══════════════════════════════════════════
#  MAIN DISPATCH
# ═══════════════════════════════════════════

CHART_TYPES = {
    "portfolio": chart_portfolio,
    "distribution": chart_distribution,
    "expiry": chart_expiry,
    "categories": chart_categories,
    "generator": chart_generator,
    "platform": chart_platform,
    "network": chart_network,
}


def generate_chart(chart_type, domains, params=None):
    """
    Generate a chart PNG.

    Args:
        chart_type: one of CHART_TYPES keys
        domains: list of domain dicts from domains.json
        params: dict of chart-specific parameters

    Returns:
        PNG bytes, or None if chart type unknown or matplotlib unavailable
    """
    if not HAS_MPL:
        return None

    func = CHART_TYPES.get(chart_type)
    if not func:
        return None

    try:
        return func(domains, params)
    except Exception as e:
        import sys
        sys.stderr.write(f"  Chart generation failed ({chart_type}): {e}\n")
        return None


def list_chart_types():
    """Return available chart types with descriptions."""
    return {
        "portfolio": "Top domains by value (bar chart)",
        "distribution": "Value distribution histogram (log scale)",
        "expiry": "Domain expiration timeline by month",
        "categories": "Domains grouped by category (pie + bar)",
        "generator": "Custom chart — plug in your own numbers",
        "platform": "Platform health dashboard (6 panels)",
        "network": "Domain network map (scatter clusters)",
    }
