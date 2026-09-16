from reportlab.lib.pagesizes import A4, landscape
from reportlab.pdfgen import canvas
from reportlab.lib import colors
from reportlab.lib.units import mm
import math, random

# ── Parse data ───────────────────────────────────────────────────────────────
data = []
with open("D:/DEV/Python/STRIP_MAP_mAKER/road_100m_intervals.txt") as f:
    for line in f:
        parts = line.strip().split()
        if len(parts) == 4:
            data.append((int(parts[0]), int(parts[1]), parts[2], parts[3]))

# ── Mappings ─────────────────────────────────────────────────────────────────
condition_colors = {
    "Baik":         colors.HexColor("#00FF0D"),
    "Sedang":       colors.HexColor("#F9EE25"),
    "Rusak_Ringan": colors.HexColor("#FF8000"),
    "Rusak_Berat":  colors.HexColor("#FF0000"),
}
condition_labels = {
    "Baik":         "Baik",
    "Sedang":       "Sedang",
    "Rusak_Ringan": "Rusak Ringan",
    "Rusak_Berat":  "Rusak Berat",
}
surface_colors = {
    "Eksisting_Aspal":  colors.HexColor("#424242"),
    "Eksisting_Beton":  colors.HexColor("#90A4AE"),
    "Kerikil":          colors.HexColor("#BCAAA4"),
    "Jembatan":         colors.HexColor("#1565C0"),
}
surface_labels = {
    "Eksisting_Aspal":  "Aspal",
    "Eksisting_Beton":  "Beton",
    "Kerikil":          "Kerikil / Tanah",
    "Jembatan":         "Jembatan",
}

# ── Page geometry ─────────────────────────────────────────────────────────────
PAGE_W, PAGE_H = landscape(A4)
MARGIN_L  = 16*mm
MARGIN_R  = 16*mm
MARGIN_T  = 24*mm
MARGIN_B  = 34*mm
DRAW_W    = PAGE_W - MARGIN_L - MARGIN_R

COND_H    = 14*mm
SURF_H    = 10*mm
GAP       = 14*mm   # wider gap for distance annotations
TICK_MAJ  = 4*mm
TICK_MIN  = 2.5*mm

ROAD_NAME = "Panca Karya - Maribung"
RUAS_NO   = "15.03.02.010"

SEGMENT_M = 2000
scale     = DRAW_W / SEGMENT_M

total_start = data[0][0]
total_end   = data[-1][1]
pages_needed = math.ceil((total_end - total_start) / SEGMENT_M)

out_path = "D:/DEV/Python/STRIP_MAP_mAKER/StripMap.pdf"
c = canvas.Canvas(out_path, pagesize=landscape(A4))

# ── Surface pattern ──────────────────────────────────────────────────────────
def draw_surface_pattern(c, x, y, w, h, stype):
    c.saveState()
    p = c.beginPath(); p.rect(x, y, w, h)
    c.clipPath(p, stroke=0, fill=0)
    c.setLineWidth(0.5)
    if stype == "Eksisting_Aspal":
        c.setStrokeColor(colors.HexColor("#212121"))
        step = 3
        xi = x - h
        while xi < x + w + h:
            c.line(xi, y, xi + h, y + h)
            xi += step
    elif stype == "Eksisting_Beton":
        c.setStrokeColor(colors.HexColor("#37474F"))
        bw, bh = 3, 3
        xi = x
        while xi < x + w:
            yi = y
            while yi < y + h:
                c.rect(xi, yi, bw, bh, fill=0, stroke=1)
                yi += bh
            xi += bw
    elif stype == "Kerikil":
        c.setFillColor(colors.HexColor("#6D4C41"))
        random.seed(99)
        for _ in range(int(w * h / 5)):
            rx = random.uniform(x + 1, x + w - 1)
            ry = random.uniform(y + 1, y + h - 1)
            r  = random.uniform(0.8, 1.8)
            c.circle(rx, ry, r, stroke=0, fill=1)
    elif stype == "Jembatan":
        c.setStrokeColor(colors.HexColor("#0D47A1"))
        c.setLineWidth(1.0)
        step = 6
        xi = x - h
        while xi < x + w + h:
            c.line(xi, y, xi + h, y + h)
            c.line(xi + h, y, xi, y + h)
            xi += step
    c.restoreState()

# ── Collect homogeneous runs for distance labels ─────────────────────────────
def get_runs(data, seg_start, seg_end, field_idx):
    """Merge consecutive segments with same value in field_idx (2=cond, 3=surf)."""
    runs = []
    for row in data:
        vis_s = max(row[0], seg_start)
        vis_e = min(row[1], seg_end)
        if vis_s >= vis_e:
            continue
        val = row[field_idx]
        if runs and runs[-1][2] == val:
            runs[-1] = (runs[-1][0], vis_e, val)
        else:
            runs.append((vis_s, vis_e, val))
    return runs

# ── Draw page ────────────────────────────────────────────────────────────────
def draw_page(c, page_num, seg_start, seg_end):
    c.setFillColor(colors.white)
    c.rect(0, 0, PAGE_W, PAGE_H, fill=1, stroke=0)

    ox = MARGIN_L

    # Strip vertical positions
    mid_y   = (PAGE_H - MARGIN_T - MARGIN_B) / 2 + MARGIN_B
    cond_y   = mid_y + GAP / 2
    surf_y   = mid_y - GAP / 2 - SURF_H
    cond_top = cond_y + COND_H
    surf_bot = surf_y

    # ── Title block ──────────────────────────────────────────────────────────
    title_y = PAGE_H - 10*mm
    c.setFont("Helvetica-Bold", 11)
    c.setFillColor(colors.black)
    sta_s_lbl = f"STA {seg_start//1000}+{seg_start%1000:03d}"
    sta_e_lbl = f"STA {seg_end//1000}+{seg_end%1000:03d}"
    c.drawCentredString(PAGE_W/2, title_y,
        f"PETA STRIP KONDISI JALAN  —  {sta_s_lbl} s/d {sta_e_lbl}")

    c.setFont("Helvetica-Bold", 9)
    c.setFillColor(colors.HexColor("#1A237E"))
    c.drawCentredString(PAGE_W/2, title_y - 5*mm,
        f"Ruas Jalan: {ROAD_NAME}  |  No. Ruas: {RUAS_NO}")

    c.setFont("Helvetica", 8)
    c.setFillColor(colors.black)
    c.drawString(MARGIN_L, title_y, f"Lembar {page_num} / {pages_needed}")
    c.drawRightString(PAGE_W - MARGIN_R, title_y, "Skala: 1 : 20.000 (approx)")

    # ── Rotated row labels (left of each strip) ──────────────────────────────
    lbl_x = MARGIN_L - 1.25*mm
    for (lbl, cy, ch) in [("KONDISI JALAN", cond_y + 1.5*mm , COND_H),
                           ("JENIS PERKERASAN", surf_y + 2.75*mm, SURF_H)]:
        c.saveState()
        c.setFont("Helvetica-Bold", 6.5)
        c.setFillColor(colors.HexColor("#333333"))
        c.translate(lbl_x, cy + ch / 2)
        c.rotate(90)
        c.drawCentredString(0, 0, lbl)
        c.restoreState()

    # ── Draw condition segments ───────────────────────────────────────────────
    for (sta_s, sta_e, cond, surf) in data:
        vis_s = max(sta_s, seg_start)
        vis_e = min(sta_e, seg_end)
        if vis_s >= vis_e:
            continue
        x0 = ox + (vis_s - seg_start) * scale
        w  = (vis_e - vis_s) * scale

        c.setFillColor(condition_colors.get(cond, colors.grey))
        c.rect(x0, cond_y, w, COND_H, fill=1, stroke=0)
        c.setStrokeColor(colors.HexColor("#33333344"))
        c.setLineWidth(0.2)
        c.rect(x0, cond_y, w, COND_H, fill=0, stroke=1)

        c.setFillColor(surface_colors.get(surf, colors.grey))
        c.rect(x0, surf_y, w, SURF_H, fill=1, stroke=0)
        draw_surface_pattern(c, x0, surf_y, w, SURF_H, surf)
        c.setStrokeColor(colors.HexColor("#33333344"))
        c.setLineWidth(0.2)
        c.rect(x0, surf_y, w, SURF_H, fill=0, stroke=1)

    # ── Outer strip borders ───────────────────────────────────────────────────
    c.setStrokeColor(colors.black)
    c.setLineWidth(0.8)
    c.rect(ox, cond_y, DRAW_W, COND_H, fill=0, stroke=1)
    c.rect(ox, surf_y, DRAW_W, SURF_H, fill=0, stroke=1)

    # ── Station ticks ─────────────────────────────────────────────────────────
    sta = int(math.ceil(seg_start / 100.0)) * 100
    while sta <= seg_end:
        x = ox + (sta - seg_start) * scale
        is_maj = (sta % 500 == 0)
        tk = TICK_MAJ if is_maj else TICK_MIN
        lw = 0.8 if is_maj else 0.4
        sc = colors.black if is_maj else colors.HexColor("#555555")
        c.setStrokeColor(sc); c.setLineWidth(lw)
        c.line(x, cond_top, x, cond_top + tk)
        c.line(x, cond_y, x, surf_y + SURF_H)   # through gap
        c.line(x, surf_bot, x, surf_bot - tk)
        if is_maj:
            label = f"{sta//1000}+{sta%1000:03d}"
            c.setFont("Helvetica-Bold", 6.5)
            c.setFillColor(colors.black)
            c.drawCentredString(x, cond_top + tk + 1.5*mm, label)
            c.drawCentredString(x, surf_bot - tk - 3*mm, label)
        sta += 100

    # ── Distance annotations in the gap ──────────────────────────────────────
    # Merge runs per surface type and draw bracket + distance label in the gap
    GAP_MID = surf_y + SURF_H + GAP / 2     # vertical centre of gap
    BRAK_Y_TOP = surf_y + SURF_H + 1*mm     # top edge bracket line y
    BRAK_Y_BOT = cond_y - 1*mm              # bottom edge bracket line y
    TEXT_Y  = GAP_MID - 1.5*mm

    surf_runs = get_runs(data, seg_start, seg_end, 3)
    for (rs, re, surf) in surf_runs:
        rx0 = ox + (rs - seg_start) * scale
        rx1 = ox + (re - seg_start) * scale
        rw  = rx1 - rx0
        dist_m = re - rs
        dist_lbl = f"{dist_m} m" if dist_m < 1000 else f"{dist_m/1000:.2f} km"
        lbl_full = f"{surface_labels.get(surf, surf)} ({dist_lbl})"

        # Only draw if wide enough
        if rw < 6:
            continue

        scol = surface_colors.get(surf, colors.grey)
        # Bracket lines
        c.setStrokeColor(scol)
        c.setLineWidth(0.7)
        # vertical serifs
        c.line(rx0 + 1, BRAK_Y_TOP, rx0 + 1, BRAK_Y_BOT)
        c.line(rx1 - 1, BRAK_Y_TOP, rx1 - 1, BRAK_Y_BOT)
        # horizontal bar
        c.line(rx0 + 1, GAP_MID, rx1 - 1, GAP_MID)

        # Label — clip to strip width
        c.saveState()
        p = c.beginPath(); p.rect(rx0, BRAK_Y_TOP, rw, BRAK_Y_BOT - BRAK_Y_TOP)
        c.clipPath(p, stroke=0, fill=0)
        c.setFillColor(colors.black)
        fs = 6.5
        c.setFont("Helvetica", fs)
        tw = c.stringWidth(lbl_full, "Helvetica", fs)
        if tw <= rw - 2:
            c.drawCentredString((rx0 + rx1) / 2, TEXT_Y, lbl_full)
        else:
            # Abbreviate: just distance
            short = dist_lbl
            if c.stringWidth(short, "Helvetica", fs) <= rw - 2:
                c.drawCentredString((rx0 + rx1) / 2, TEXT_Y, short)
        c.restoreState()

# ── End stationing marker ─────────────────────────────────────────────────
    # Mark the last data point on the final page only
    if seg_end == total_end:
        x_end = ox + (total_end - seg_start) * scale
        end_label = f"{total_end//1000}+{total_end%1000:03d}"

        # Bold vertical line spanning both strips
        c.setStrokeColor(colors.HexColor("#B71C1C"))
        c.setLineWidth(1.5)
        c.line(x_end, surf_bot - TICK_MAJ, x_end, cond_top + TICK_MAJ)

        # Triangle marker above condition strip
        tri_size = 3*mm
        p = c.beginPath()
        p.moveTo(x_end, cond_top + TICK_MAJ + tri_size)
        p.lineTo(x_end - tri_size/2, cond_top + TICK_MAJ)
        p.lineTo(x_end + tri_size/2, cond_top + TICK_MAJ)
        p.close()
        c.setFillColor(colors.HexColor("#B71C1C"))
        c.drawPath(p, fill=1, stroke=0)

        # Label
        c.setFont("Helvetica-Bold", 7)
        c.setFillColor(colors.HexColor("#B71C1C"))
        c.drawCentredString(x_end, cond_top + TICK_MAJ + tri_size + 1.5*mm, end_label)
        c.setFont("Helvetica", 6)
        c.drawCentredString(x_end, cond_top + TICK_MAJ + tri_size + 4.5*mm, "(AKHIR RUAS)")

    c.setFont("Helvetica", 7)
    c.setFillColor(colors.HexColor("#444444"))
    c.drawCentredString(PAGE_W/2, cond_top + TICK_MAJ + 5.5*mm, "Stationing (STA)")

    # ── Legend ────────────────────────────────────────────────────────────────
    leg_y  = MARGIN_B - 11*mm
    leg_bh = 5*mm
    leg_bw = 14*mm
    col_gap= 44*mm

    c.setFont("Helvetica-Bold", 8)
    c.setFillColor(colors.black)
    c.drawString(MARGIN_L, leg_y + 12*mm, "KONDISI JALAN:")
    lx = MARGIN_L + 32*mm
    for key, col in condition_colors.items():
        c.setFillColor(col)
        c.setStrokeColor(colors.black); c.setLineWidth(0.5)
        c.rect(lx, leg_y + 10*mm, leg_bw, leg_bh, fill=1, stroke=1)
        c.setFillColor(colors.black); c.setFont("Helvetica", 7.5)
        c.drawString(lx + leg_bw + 1.5*mm, leg_y + 11.5*mm, condition_labels[key])
        lx += col_gap

    c.setFont("Helvetica-Bold", 8)
    c.setFillColor(colors.black)
    c.drawString(MARGIN_L, leg_y + 3*mm, "JENIS PERKERASAN:")
    lx = MARGIN_L + 32*mm
    for key, scol in surface_colors.items():
        c.setFillColor(scol)
        c.setStrokeColor(colors.black); c.setLineWidth(0.5)
        c.rect(lx, leg_y + 1*mm, leg_bw, leg_bh, fill=1, stroke=1)
        draw_surface_pattern(c, lx, leg_y + 1*mm, leg_bw, leg_bh, key)
        c.setFillColor(colors.black); c.setFont("Helvetica", 7.5)
        c.drawString(lx + leg_bw + 1.5*mm, leg_y + 2.5*mm, surface_labels[key])
        lx += col_gap

    # ── Frame ─────────────────────────────────────────────────────────────────
    c.setStrokeColor(colors.HexColor("#222222"))
    c.setLineWidth(1.2)
    c.rect(MARGIN_L - 4*mm, MARGIN_B - 13*mm,
           DRAW_W + 8*mm, PAGE_H - MARGIN_T - MARGIN_B + 10*mm,
           fill=0, stroke=1)


for pg in range(pages_needed):
    seg_start = total_start + pg * SEGMENT_M
    seg_end   = min(total_start + (pg + 1) * SEGMENT_M, total_end)
    draw_page(c, pg + 1, seg_start, seg_end)
    c.showPage()

c.save()
print(f"Selesai! {pages_needed} halaman → {out_path}")