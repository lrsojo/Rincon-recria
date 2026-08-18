"""
update_data.py
Fetchea los 4 Google Sheets de recría, procesa los datos
y actualiza recria_live.html con datos frescos.
Se ejecuta via GitHub Actions automáticamente.
"""
import requests, json, csv, io, re, os
from datetime import datetime
from collections import defaultdict

# ── URLS DE GOOGLE SHEETS (publicados como CSV) ───────────────────────────────
SHEETS = {
    '2023': 'https://docs.google.com/spreadsheets/d/e/2PACX-1vScV-vZEvvwh_gI_ztF2vR9hukUTgHIgXEAtK0Ub6CYctO0I-1f8dgP4F0p9IM5JySYhhiJCauqTOtW/pub?gid=1353830390&single=true&output=csv',
    '2024': 'https://docs.google.com/spreadsheets/d/e/2PACX-1vTu1fl5fuFXxbo9Wtkb-a-yOmqojs9P3CUFxClZVed6iZ7dh-LZVLsvNpiCbXkDXB6UeHTEKb-6HTUq/pub?output=csv',
    '2025': 'https://docs.google.com/spreadsheets/d/e/2PACX-1vST2aXurt0cjEBvVkNu37XnRoRbcwc0EGidMBWrK57PzrAhZEKeoznE63TwEENJhsvPBZRN35CpmR1i/pub?gid=1353830390&single=true&output=csv',
    '2026': 'https://docs.google.com/spreadsheets/d/e/2PACX-1vSk2RcOleSKx7VZLyuS3z061ZkHn6eexA1EHvzRTNttFelCjKo9lk_KANBrvpfGp8y_v7q3S3s7TfpA/pub?gid=1353830390&single=true&output=csv',
}

PESO_COLS = ['DESTETE PESO 1','PESADA 1 PESO','PESADA 2 PESO','PESADA 3 PESO','PESADA 4 PESO','PESADA 5 PESO']
DATE_COLS = ['DESTETE FECHA 1','PESADA 1 FECHA','PESADA 2 FECHA','PESADA 3 FECHA','PESADA 4 FECHA','PESADA 5 FECHA']

R2_NORM = {
    'Hembras cabeza':'Cabeza','Machos Cabeza':'Cabeza','CABEZA HEMBRAS':'Cabeza','CABEZA MACHOS':'Cabeza',
    'CAbeza':'Cabeza','cabeza':'Cabeza','Cabeza':'Cabeza','Hembras Cabeza':'Cabeza','Machos cabeza':'Cabeza',
    'Cuerpo mixto':'Cuerpo','CUERPO MIXTO':'Cuerpo','Cuerpo':'Cuerpo','cuerpo':'Cuerpo',
    'Cola Mixto':'Cola','COLA':'Cola','Cola':'Cola','Cola 2':'Cola','cola 2':'Cola',
}

def to_num(s):
    try: return float(str(s).replace(',','.'))
    except: return None

def parse_date(s):
    if not s or str(s).strip() in ('','SIN PESAR'): return None
    for fmt in ('%d/%m/%Y','%d/%m/%y','%d-%m-%Y'):
        try: return datetime.strptime(str(s).strip(), fmt)
        except: pass
    return None

def day_of_year(d):
    return d.timetuple().tm_yday if d else None

def day_to_label(day):
    months = ['Ene','Feb','Mar','Abr','May','Jun','Jul','Ago','Sep','Oct','Nov','Dic']
    import datetime as dt
    base = dt.date(2025, 1, 1) + dt.timedelta(days=day-1)
    return f"{base.day:02d}-{months[base.month-1]}"

def median_day(days):
    if not days: return None
    s = sorted(days)
    m = len(s)//2
    return s[m]

def compute_series(rows):
    pts, bars = [], []
    for pf, df in zip(PESO_COLS, DATE_COLS):
        data = []
        for row in rows:
            p = to_num(row.get(pf,''))
            d = parse_date(row.get(df,''))
            if p and d and 30 < p < 900:
                data.append((day_of_year(d), p))
        if len(data) < 5: continue
        days = [x[0] for x in data]
        pesos = [x[1] for x in data]
        med = median_day(days)
        pts.append({
            'label': day_to_label(med),
            'day': med,
            'peso': round(sum(pesos)/len(pesos), 1),
            'n': len(pesos)
        })
    for i in range(len(pts)-1):
        p0, p1 = pts[i], pts[i+1]
        days = p1['day'] - p0['day']
        if days > 0:
            bars.append({
                'day': p1['day'],
                'gdp': round((p1['peso']-p0['peso'])/days, 3),
                'dias': days,
                'label': f"{p0['label']}→{p1['label']}"
            })
    return {'points': pts, 'bars': bars}

def fetch_sheet(url, year):
    print(f"  Fetching {year}...")
    try:
        r = requests.get(url, timeout=30, headers={'User-Agent': 'Mozilla/5.0'})
        r.raise_for_status()
        text = r.text
        if 'SEXO' not in text or 'DESTETE' not in text:
            raise ValueError("No es CSV válido")
        return text
    except Exception as e:
        print(f"  ERROR {year}: {e}")
        return None

def process_sheet(csv_text, year):
    reader = csv.DictReader(io.StringIO(csv_text))
    rows = []
    for row in reader:
        sexo = row.get('SEXO','').strip()
        if sexo not in ('Macho','Hembra'): continue
        d = parse_date(row.get('DESTETE FECHA 1',''))
        if not d or d.year != int(year): continue
        p = to_num(row.get('DESTETE PESO 1',''))
        if not p or p <= 60: continue
        row['_r2'] = R2_NORM.get(row.get('Rodeo 2',''), None)
        row['_r1'] = row.get('Rodeo 1','').strip()
        rows.append(row)
    return rows

def build_precomp(rows, year):
    result = {}
    main = [r for r in rows if r.get('_r2')]
    result['__ALL__'] = compute_series(main)
    for sx in ['Macho','Hembra']:
        sub = [r for r in main if r.get('SEXO')==sx]
        if len(sub)>10: result[f'sexo:{sx}'] = compute_series(sub)
    for r2 in ['Cabeza','Cuerpo','Cola']:
        sub = [r for r in main if r.get('_r2')==r2]
        if len(sub)>10: result[f'r2:{r2}'] = compute_series(sub)
    for sx in ['Macho','Hembra']:
        for r2 in ['Cabeza','Cuerpo','Cola']:
            sub = [r for r in main if r.get('SEXO')==sx and r.get('_r2')==r2]
            if len(sub)>10: result[f'sexo:{sx}|r2:{r2}'] = compute_series(sub)
    r1s = set(r['_r1'] for r in main if r['_r1'])
    for r1 in r1s:
        sub = [r for r in main if r['_r1']==r1]
        if len(sub)>10: result[f'r1:{r1}'] = compute_series(sub)
    return result

# ── MAIN ──────────────────────────────────────────────────────────────────────
print("Actualizando datos del dashboard de recría...")
precomp = {}
r1_by_year = {}

for yr, url in SHEETS.items():
    csv_text = fetch_sheet(url, yr)
    if not csv_text:
        print(f"  Saltando {yr} por error de fetch")
        precomp[yr] = {}
        r1_by_year[yr] = []
        continue
    rows = process_sheet(csv_text, yr)
    precomp[yr] = build_precomp(rows, yr)
    r1_by_year[yr] = [k.replace('r1:','') for k in precomp[yr] if k.startswith('r1:')]
    pts = precomp[yr].get('__ALL__',{}).get('points',[])
    if pts:
        last = pts[-1]
        print(f"  {yr}: {len(pts)} pesadas. Último: {last['label']} {last['peso']}kg n={last['n']}")

# ── ACTUALIZAR HTML ───────────────────────────────────────────────────────────
now = datetime.now().strftime('%d/%m/%Y %H:%M')
precomp_json = json.dumps(precomp)
r1_json = json.dumps(r1_by_year)

html_file = 'recria_live.html'
with open(html_file, 'r', encoding='utf-8') as f:
    html = f.read()

# Replace PRECOMP data between markers
replacement = f'// ##DATA_START##\nconst PRECOMP={precomp_json};\nconst R1_BY_YEAR_INIT={r1_json};\nconst LAST_UPDATE="{now}";\n// ##DATA_END##'
html = re.sub(
    r'// ##DATA_START##.*?// ##DATA_END##',
    lambda m: replacement,
    html, flags=re.DOTALL
)

with open(html_file, 'w', encoding='utf-8') as f:
    f.write(html)

print(f"\nDashboard actualizado: {now}")
