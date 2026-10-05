"""
uji_skenario_chatbot.py -- pengujian otomatis (black-box) untuk dokumen
"Skenario Pengujian Chatbot Rekomendasi Skincare". Tiap skenario dicetak
PASS/FAIL beserta buktinya, jadi hasilnya bisa langsung dipakai di Bab IV.

Syarat: backend jalan di BACKEND_URL (default http://127.0.0.1:8000).
Form onboarding diuji pakai streamlit.testing (AppTest) -- halaman Streamlit
yang asli dijalankan tanpa browser.

CARA PAKAI (dari root project):
    python tests/uji_skenario_chatbot.py            # semua bagian
    python tests/uji_skenario_chatbot.py --bagian 1  # bagian tertentu
"""
import argparse
import os
import sys
from pathlib import Path

import requests

BACKEND_URL = os.getenv("BACKEND_URL", "http://127.0.0.1:8000")
ROOT = Path(__file__).resolve().parent.parent
TIMEOUT_CHAT = 120

PROFIL_KERING = {"tipe_kulit": "kering", "masalah_kulit": ["jerawat"], "budget": 150000}
_hasil = []


def cek(kode, deskripsi, lulus, bukti=""):
    _hasil.append((kode, deskripsi, bool(lulus), bukti))
    print(f"  [{'PASS' if lulus else 'FAIL'}] {kode} {deskripsi}" + (f"\n         bukti: {bukti}" if bukti else ""))


_BOCOR = []  # (pesan, bagian respons, cuplikan) -- nilai kosong yang lolos mentah ke user (8.4)
_POLA_BOCOR = __import__("re").compile(r"\b(nan|NaN|None|null|undefined)\b")


def _cek_bocor(pesan, d):
    """Setiap respons chat di SEMUA bagian dipindai: tidak boleh ada nan/None
    mentah di teks yang dilihat user (penjelasan, kartu, tabel)."""
    teks = [("penjelasan", d.get("explanation") or "")]
    for x in d.get("recommendation") or []:
        teks += [("alasan kartu", x.get("alasan") or ""), ("nama kartu", str(x.get("produk"))),
                 ("brand kartu", str(x.get("brand") or ""))] + [("catatan kartu", c) for c in x.get("catatan") or []]
    for b in (d.get("perbandingan") or {}).get("baris", []):
        teks += [(f"tabel {b['atribut']}", str(v)) for v in b["nilai"]]
    for bagian, t in teks:
        m = _POLA_BOCOR.search(t)
        if m:
            _BOCOR.append((pesan, bagian, t[max(0, m.start() - 40):m.end() + 20]))


def chat(pesan, onboarding=None, konteks=None):
    body = {"message": pesan, "onboarding": onboarding or PROFIL_KERING, "konteks": konteks}
    r = requests.post(f"{BACKEND_URL}/chat", json=body, timeout=TIMEOUT_CHAT)
    d = r.json()
    if r.status_code == 200:
        _cek_bocor(pesan, d)
    return r.status_code, d


def _tipe_cocok(produk_id, tipe, katalog):
    """Tag tipe kulit kosong (NaN) = belum diketahui -> boleh lolos (skenario 8.1)."""
    tag = katalog.get(produk_id)
    return not isinstance(tag, str) or not tag.strip() or tipe in [t.strip() for t in tag.split(";")]


# ---------------- BAGIAN 1: onboarding (form) & ganti profil lewat chat ----------------

def _app_onboarding():
    from streamlit.testing.v1 import AppTest
    if str(ROOT / "frontend") not in sys.path:  # `streamlit run` menambahkan ini otomatis, AppTest tidak
        sys.path.insert(0, str(ROOT / "frontend"))
    at = AppTest.from_file(str(ROOT / "frontend" / "app.py"), default_timeout=TIMEOUT_CHAT)
    at.run()
    return at


def _isi_form(at, tipe=None, masalah=None, budget=None, tanpa_batas=False):
    if tipe is not None:
        at.selectbox[0].set_value(tipe)
    if masalah is not None:
        at.multiselect[0].set_value(masalah)
    if budget is not None:
        at.number_input[0].set_value(budget)
    if tanpa_batas:
        at.checkbox[0].check()
    at.button[0].click()
    at.run()
    return " | ".join(e.value for e in at.error)


def uji_bagian_1():
    print("\n=== BAGIAN 1: Onboarding (form) & ganti profil lewat chat ===")
    semua_masalah = ["jerawat", "kusam", "hiperpigmentasi", "penuaan", "kemerahan_iritasi", "dehidrasi"]

    # 1.1 form lengkap & valid -> chat langsung jalan pakai profil ini
    at = _app_onboarding()
    err = _isi_form(at, "berminyak", ["jerawat", "kusam"], 100000)
    ob = at.session_state["onboarding"]
    masuk_chat = at.session_state["onboarding_selesai"] and len(at.chat_input) == 1
    at.chat_input[0].set_value("rekomendasiin dong").run()
    riwayat = at.session_state["riwayat_pesan"]
    jawaban = riwayat[-1] if riwayat else {}
    profil_chat = (at.session_state["konteks"] or {}).get("profil", {})
    cek("1.1", "Form lengkap & valid -> submit sukses, chat pakai profil form tanpa tanya ulang",
        not err and masuk_chat and ob["masalah_kulit"] == ["jerawat", "kusam"] and jawaban.get("produk")
        and profil_chat.get("tipe_kulit") == "berminyak" and profil_chat.get("budget_max") == 100000,
        f"error form={err!r}, masuk chat={masuk_chat}, produk tampil={len(jawaban.get('produk', []))}, "
        f"profil dipakai={profil_chat}")

    # 1.2 tipe kulit kosong
    at = _app_onboarding()
    err = _isi_form(at, None, ["jerawat"], 100000)
    cek("1.2", "Tipe kulit tidak dipilih -> form menolak + pesan error jelas",
        "Pilih tipe kulit" in err and not at.session_state["onboarding_selesai"], f"pesan error: {err!r}")

    # 1.3 masalah kulit kosong
    at = _app_onboarding()
    err = _isi_form(at, "kering", [], 100000)
    cek("1.3", "Masalah kulit tidak dipilih -> form menolak + pesan error jelas",
        "minimal 1 masalah kulit" in err and not at.session_state["onboarding_selesai"], f"pesan error: {err!r}")

    # 1.4 semua masalah dipilih -> semua masuk sebagai list (form -> backend -> konteks)
    at = _app_onboarding()
    err = _isi_form(at, "normal", semua_masalah, 200000)
    ob = at.session_state["onboarding"]
    status, data = chat("rekomendasiin dong", ob)
    masalah_backend = data.get("konteks", {}).get("profil", {}).get("masalah_kulit", [])
    cek("1.4", "Semua 6 masalah dipilih -> keenamnya masuk ke masalah_kulit, tidak ada yang keskip",
        not err and ob["masalah_kulit"] == semua_masalah and sorted(masalah_backend) == sorted(semua_masalah),
        f"form={ob['masalah_kulit']}, dipakai backend={masalah_backend}")

    # 1.5 budget kosong & checkbox tidak dicentang -> ditolak
    at = _app_onboarding()
    err = _isi_form(at, "kering", ["kusam"], None)
    cek("1.5", "Budget dikosongkan & checkbox tanpa batas tidak dicentang -> ditolak",
        "Isi budget" in err and not at.session_state["onboarding_selesai"], f"pesan error: {err!r}")

    # 1.5b checkbox tanpa batas dicentang -> lolos dengan budget None; kalau angka juga diisi, checkbox menang
    hasil_cb = {}
    for nama, angka in (("angka kosong", None), ("angka diisi 50000", 50000)):
        at = _app_onboarding()
        err = _isi_form(at, "kering", ["kusam"], angka, tanpa_batas=True)
        ob = at.session_state["onboarding"]
        status, data = chat("rekomendasiin dong", ob)
        hasil_cb[nama] = (err, at.session_state["onboarding_selesai"], ob["budget"],
                          data.get("konteks", {}).get("profil", {}).get("budget_max", "?"))
    s_api, d_api = chat("rekomendasiin dong", {**PROFIL_KERING, "budget": 50000, "tanpa_batas_budget": True})
    cek("1.5b", "Checkbox tanpa batas dicentang -> lolos, budget_max=None; kalau angka juga diisi, checkbox menang",
        all(not e and selesai and b is None and bm is None for e, selesai, b, bm in hasil_cb.values())
        and s_api == 200 and d_api["konteks"]["profil"]["budget_max"] is None,
        "; ".join(f"{n}: error={e!r}, lolos={s}, budget form={b}, budget_max dipakai backend={bm}"
                  for n, (e, s, b, bm) in hasil_cb.items())
        + f"; API budget=50000+tanpa_batas -> budget_max={d_api['konteks']['profil']['budget_max']}")

    # 1.6 budget 0
    at = _app_onboarding()
    err = _isi_form(at, "kering", ["kusam"], 0)
    cek("1.6", "Budget 0 -> ditolak, minta angka > 0",
        "lebih dari 0" in err and not at.session_state["onboarding_selesai"], f"pesan error: {err!r}")

    # 1.7 budget negatif / bukan angka -> ditolak di form DAN di backend
    at = _app_onboarding()
    err = _isi_form(at, "kering", ["kusam"], -50000)
    kasus_api = {
        "budget -50000": {**PROFIL_KERING, "budget": -50000},
        "budget 0": {**PROFIL_KERING, "budget": 0},
        "budget 'abc'": {**PROFIL_KERING, "budget": "abc"},
        "budget kosong": {**PROFIL_KERING, "budget": None},
        "tipe kosong": {**PROFIL_KERING, "tipe_kulit": ""},
        "masalah kosong": {**PROFIL_KERING, "masalah_kulit": []},
        "masalah ngasal": {**PROFIL_KERING, "masalah_kulit": ["ketombe"]},
    }
    hasil_api = {nama: chat("rekomendasiin dong", ob) for nama, ob in kasus_api.items()}
    semua_400 = all(s == 400 for s, _ in hasil_api.values())
    cek("1.7", "Budget negatif/bukan angka ditolak di form, dan backend juga menolak request langsung",
        "lebih dari 0" in err and not at.session_state["onboarding_selesai"] and semua_400,
        f"form: {err!r}; API: " + "; ".join(f"{n} -> {s} {d.get('detail')!r}" for n, (s, d) in hasil_api.items()))

    # 1.8 budget sangat besar
    status, data = chat("rekomendasiin dong", {**PROFIL_KERING, "budget": 999999999999})
    status2, data2 = chat("rekomendasiin dong", {**PROFIL_KERING, "budget": 10 ** 20})
    cek("1.8", "Budget sangat besar -> tidak error/overflow, filter tetap jalan",
        status == 200 and data.get("recommendation") and status2 == 200 and data2.get("recommendation"),
        f"999999999999 -> {status}, {len(data.get('recommendation', []))} produk; "
        f"10^20 -> {status2}, {len(data2.get('recommendation', []))} produk")

    # 1.9 ganti tipe kulit lewat chat (+ typo/sinonim, + tidak dikenal -> tanya ulang)
    import pandas as pd
    katalog = pd.read_csv(ROOT / "data" / "products_final.csv").set_index("id")["tipe_kulit_cocok"].to_dict()
    _, awal = chat("rekomendasiin dong")
    _, ganti = chat("eh aku kombinasi deng, bukan kering", konteks=awal["konteks"])
    p = ganti["konteks"]["profil"]
    produk_ok = all(_tipe_cocok(x["id"], "kombinasi", katalog) for x in ganti["recommendation"])
    _, lanjut = chat("rekomendasiin lagi dong", konteks=ganti["konteks"])
    tetap = lanjut["konteks"]["profil"]["tipe_kulit"]
    sinonim = {teks: chat(teks)[1]["konteks"]["profil"]["tipe_kulit"]
               for teks in ("kulitku berminyk", "kulit oily", "kulit campuran")}
    _, tanya = chat("kulitku sebenernya xyz", konteks=awal["konteks"])
    _, jawab = chat("kombinasi", konteks=tanya["konteks"])
    cek("1.9", "Ganti tipe kulit lewat chat -> profil ter-update & dipakai seterusnya; typo/sinonim dikenali; "
               "tidak dikenal -> tanya ulang",
        p["tipe_kulit"] == "kombinasi" and "kombinasi" in ganti["explanation"] and ganti["recommendation"]
        and produk_ok and tetap == "kombinasi"
        and sinonim == {"kulitku berminyk": "berminyak", "kulit oily": "berminyak", "kulit campuran": "kombinasi"}
        and tanya["tipe"] == "klarifikasi" and not tanya["recommendation"]
        and tanya["konteks"]["profil"]["tipe_kulit"] == "kering"
        and jawab["konteks"]["profil"]["tipe_kulit"] == "kombinasi" and jawab["recommendation"],
        f"setelah ganti: tipe={p['tipe_kulit']}, semua produk cocok kombinasi={produk_ok}, pesan berikutnya tetap={tetap}; "
        f"sinonim={sinonim}; 'xyz' -> {tanya['explanation']!r}; dijawab 'kombinasi' -> "
        f"{jawab['konteks']['profil']['tipe_kulit']}")

    # 1.9b (temuan uji manual): tipe_kulit dan masalah_kulit tidak boleh tertukar, dan bot tidak
    # boleh terus mengulang "Aku belum kenal tipe kulit 'kusam'" walau pengguna sudah menyebut field-nya
    def alur(pesan_list):
        konteks, hasil = None, []
        for pesan in pesan_list:
            hasil.append(chat(pesan, konteks=konteks)[1])
            konteks = hasil[-1]["konteks"]
        return hasil

    def prof(d):
        return d["konteks"]["profil"]

    tanya, sepertinya = alur(["kulitku aneh", "Kulit saya sepertinya kusam"])
    _, eksplisit = alur(["kulitku aneh", "masalah kulit saya kusam"])
    # (1) kosakata dulu, simetris: 6 masalah saat ditanya TIPE, 5 tipe saat ditanya MASALAH
    masalah_ok = {kata: (lambda d: prof(d)["masalah_kulit"] == [kunci] and prof(d)["tipe_kulit"] == "kering"
                         and d["konteks"]["menunggu"] is None and "belum kenal" not in d["explanation"])(
                             alur(["kulitku aneh", kata])[1])
                  for kata, kunci in [("jerawat", "jerawat"), ("kusam", "kusam"), ("hiperpigmentasi", "hiperpigmentasi"),
                                      ("penuaan", "penuaan"), ("kemerahan", "kemerahan_iritasi"),
                                      ("dehidrasi", "dehidrasi")]}
    tanya_masalah = alur(["masalah kulit saya aneh"])[0]
    tipe_ok = {kata: (lambda d: prof(d)["tipe_kulit"] == kata and prof(d)["masalah_kulit"] == ["jerawat"]
                      and d["konteks"]["menunggu"] is None and "belum kenal" not in d["explanation"])(
                          alur(["masalah kulit saya aneh", kata])[1])
               for kata in ("berminyak", "kering", "kombinasi", "sensitif", "normal")}
    tipe_label_masalah = alur(["tipe kulit saya jerawat"])[0]
    masalah_label_tipe = alur(["masalah kulit saya berminyak"])[0]
    # (3) gagal 2x berturut-turut -> pertanyaan lain; gagal ke-3 -> berhenti bertanya
    e1, e2, e3, e4 = alur(["kulitku aneh", "masih aneh", "masalah", "pokoknya aneh"])
    # temuan uji manual (HP): setelah "tipe atau masalah?", permintaan rekomendasi eksplisit yang
    # menyebut nama pemilik kulit ("kulit avelina") tetap dilayani, bukan dianggap gagal ke-3
    minta = alur(["kulitku aneh", "masih aneh", "Kulit avelina sangat jelek, rekomendasi agar bisa cantikkan dia"])[2]
    cek("1.9b", "Tipe kulit & masalah kulit tidak tertukar (kosakata dicek dulu, simetris untuk 6 masalah & 5 tipe); "
                "user menyebut field-nya sendiri -> mengalahkan pertanyaan yang ditunggu; gagal paham 2x -> tanya "
                "'tipe atau masalah?', bukan pertanyaan yang sama (tidak loop)",
        tanya["konteks"]["menunggu"] == "tipe_kulit"
        and prof(sepertinya)["masalah_kulit"] == ["kusam"] and sepertinya["recommendation"]
        and "belum kenal" not in sepertinya["explanation"] and sepertinya["konteks"]["menunggu"] is None
        and prof(eksplisit)["masalah_kulit"] == ["kusam"] and prof(eksplisit)["tipe_kulit"] == "kering"
        and eksplisit["recommendation"] and "belum kenal" not in eksplisit["explanation"]
        and all(masalah_ok.values()) and all(tipe_ok.values())
        and tanya_masalah["konteks"]["menunggu"] == "masalah_kulit"
        and "masalah kulit \"aneh\"" in tanya_masalah["explanation"]
        and prof(tipe_label_masalah)["masalah_kulit"] == ["jerawat"]
        and "masalah kulit, bukan tipe kulit" in tipe_label_masalah["explanation"]
        and prof(masalah_label_tipe)["tipe_kulit"] == "berminyak"
        and "tipe kulit, bukan masalah kulit" in masalah_label_tipe["explanation"]
        and e1["explanation"] != e2["explanation"] and "**tipe kulit**" in e2["explanation"]
        and "**masalah kulit**" in e2["explanation"] and e3["konteks"]["menunggu"] == "masalah_kulit"
        and e4["konteks"]["menunggu"] is None and "aku biarkan seperti sekarang" in e4["explanation"]
        and minta["recommendation"] and "aku biarkan seperti sekarang" not in minta["explanation"]
        and "belum kenal" not in minta["explanation"],
        f"saat ditanya tipe: 'Kulit saya sepertinya kusam' -> masalah={prof(sepertinya)['masalah_kulit']}, "
        f"{len(sepertinya['recommendation'])} produk, jawaban: {sepertinya['explanation'][:90]!r}; "
        f"'masalah kulit saya kusam' -> masalah={prof(eksplisit)['masalah_kulit']}, tipe tetap "
        f"{prof(eksplisit)['tipe_kulit']}; 6 masalah saat ditanya tipe={masalah_ok}; 5 tipe saat ditanya "
        f"masalah={tipe_ok}; 'tipe kulit saya jerawat' -> masalah={prof(tipe_label_masalah)['masalah_kulit']}; "
        f"'masalah kulit saya berminyak' -> tipe={prof(masalah_label_tipe)['tipe_kulit']}; gagal ke-2 -> "
        f"{e2['explanation'][:70]!r}; gagal ke-3 -> {e4['explanation'][:60]!r}; minta rekomendasi saat ditanya "
        f"'tipe atau masalah?' -> {len(minta['recommendation'])} produk, {minta['explanation'][:60]!r}")

    # 1.9c (NLU hybrid, lapis aturan) ungkapan sehari-hari & perumpamaan dipahami TANPA LLM
    harap = {"Saya baru umur 24 tapi kulit saya seperti orang 70 tahun": ("kering", ["penuaan"]),
             "mukaku kayak gorengan tiap siang": ("berminyak", ["jerawat"]),
             "kulit saya kayak kertas, ketarik terus": ("kering", ["jerawat"]),
             "abis jerawatan ninggalin bekas item item": ("kering", ["jerawat", "hiperpigmentasi"]),
             "kulit saya mulai kendur": ("kering", ["penuaan"]),
             "muka sering merah merah dan ruam": ("kering", ["kemerahan_iritasi"]),
             "kulitku kayak nenek nenek": ("kering", ["penuaan"])}
    dapat = {m: chat(m)[1] for m in harap}
    perumpamaan = {m: chat(m)[1] for m in ("kulit saya ga kayak orang tua kok", "kulit saya kayak umur 30 tahun")}
    cek("1.9c", "Ungkapan sehari-hari & perumpamaan soal kulit dipahami aturan NLU (tanpa LLM): 'kulit seperti "
                "orang 70 tahun' -> penuaan, 'kayak gorengan' -> berminyak, 'ketarik' -> kering, 'bekas item' -> "
                "hiperpigmentasi, dst; kata setelah 'seperti/kayak' tidak pernah dianggap nama tipe kulit",
        all((prof(d)["tipe_kulit"], prof(d)["masalah_kulit"]) == harap[m] and d["recommendation"]
            and "belum kenal" not in d["explanation"] for m, d in dapat.items())
        and all("belum kenal" not in d["explanation"] and "penuaan" not in prof(d)["masalah_kulit"]
                for d in perumpamaan.values()),
        f"{ {m[:38]: (prof(d)['tipe_kulit'], prof(d)['masalah_kulit']) for m, d in dapat.items()} }; "
        f"disangkal/umur muda -> {[prof(d)['masalah_kulit'] for d in perumpamaan.values()]}")

    # 1.9d (NLU hybrid, lapis LLM) aturan tidak paham -> tafsiran LLM yang divalidasi
    cbf_lokal = _mesin_lokal()  # juga menambahkan models/ ke sys.path
    import generate_jawaban
    from percakapan import Percakapan

    class _GenPalsu:  # LLM tiruan yang jawabannya diatur -> logika penggabungan diuji deterministik
        def __init__(self, jawaban):
            self.jawaban, self.dipanggil = jawaban, []

        def narasi(self, *a, **kw):
            return None

        def pahami_profil(self, pesan, menunggu=None):
            self.dipanggil.append(pesan)
            return generate_jawaban._validasi_pemahaman(self.jawaban.get(pesan), pesan)

    lengket = "pori-pori saya besar dan muka gampang lengket kalau siang"
    dagu = "di dagu sering muncul benjolan merah yang sakit"
    palsu = _GenPalsu({lengket: {"tipe_kulit": "berminyak", "masalah_kulit": [],
                                 "bukti": {"berminyak": "muka gampang lengket"}},
                       "kulit saya kayak batu": {"tipe_kulit": "kering", "masalah_kulit": [],
                                                 "bukti": {"kering": "bukti karangan"}},
                       dagu: {"tipe_kulit": "oily", "masalah_kulit": ["jerawat", "flek"],
                              "bukti": {"oily": "dagu", "jerawat": "benjolan merah yang sakit"}}})
    pc = Percakapan(cbf_lokal, palsu)
    ob_n = {"tipe_kulit": "normal", "masalah_kulit": ["kusam"], "budget": 150000}
    t_lengket, t_batu, t_dagu = (pc.proses(m, None, ob_n) for m in (lengket, "kulit saya kayak batu", dagu))
    palsu.dipanggil.clear()
    for m in list(harap)[:3] + ["rekomendasiin sunscreen buat kulitku", "siapa presiden indonesia"]:
        pc.proses(m, None, ob_n)
    tanpa_llm = list(palsu.dipanggil)
    t_mati = Percakapan(cbf_lokal, _GenPalsu({})).proses(lengket, None, ob_n)
    # bagian Groq asli: tier gratis dibatasi token per menit, dan setelah puluhan skenario
    # berturut-turut backend bisa sedang melewati LLM 60 detik -> beri jeda supaya yang diuji
    # memang tafsiran LLM, bukan batas kuota
    import time
    time.sleep(70)
    live = {}
    for m in (lengket, dagu):
        live[m] = chat(m, ob_n)[1]
        time.sleep(20)
    live_aneh = chat("kulitku aneh", ob_n)[1]
    cek("1.9d", "Kalimat yang tidak tertangkap aturan ditafsirkan LLM (nilai baku + bukti kutipan persis dari pesan, "
                "disebut terbuka ke user); bukti karangan / nilai di luar daftar ditolak; pesan yang sudah dipahami "
                "aturan tidak dikirim ke LLM; LLM mati / tidak paham -> perilaku aturan biasa",
        t_lengket["konteks"]["profil"]["tipe_kulit"] == "berminyak" and "aku tangkap" in t_lengket["explanation"]
        and t_batu["konteks"]["profil"]["tipe_kulit"] == "normal"
        and t_dagu["konteks"]["profil"]["tipe_kulit"] == "normal"
        and t_dagu["konteks"]["profil"]["masalah_kulit"] == ["jerawat"] and not tanpa_llm
        and t_mati["recommendation"] and t_mati["konteks"]["profil"]["tipe_kulit"] == "normal"
        and prof(live[lengket])["tipe_kulit"] == "berminyak" and "jerawat" in prof(live[dagu])["masalah_kulit"]
        and live_aneh["konteks"]["menunggu"] == "tipe_kulit",
        f"palsu: lengket -> {t_lengket['konteks']['profil']['tipe_kulit']}, bukti karangan -> tetap "
        f"{t_batu['konteks']['profil']['tipe_kulit']}, 'oily'/'flek' dibuang -> "
        f"{t_dagu['konteks']['profil']['masalah_kulit']}, pesan yg dikirim ke LLM padahal sudah dipahami aturan: "
        f"{tanpa_llm}; Groq asli: lengket -> {prof(live[lengket])['tipe_kulit']}, dagu -> "
        f"{prof(live[dagu])['masalah_kulit']}, jawaban: {live[dagu]['explanation'][:80]!r}; 'kulitku aneh' -> "
        f"menunggu={live_aneh['konteks']['menunggu']}")

    # 1.10 ganti sebagian profil -> field lain tetap
    _, awal = chat("rekomendasiin dong", {"tipe_kulit": "sensitif", "masalah_kulit": ["kemerahan_iritasi", "dehidrasi"],
                                          "budget": 50000})
    _, naik = chat("budgetnya naikin ke 100rb aja", {"tipe_kulit": "sensitif",
                                                    "masalah_kulit": ["kemerahan_iritasi", "dehidrasi"],
                                                    "budget": 50000}, awal["konteks"])
    p0, p1 = awal["konteks"]["profil"], naik["konteks"]["profil"]
    harga_ok = all(x["harga"] is None or x["harga"] <= 100000 for x in naik["recommendation"])
    konteks = naik["konteks"]
    budget_berikutnya = []
    for pesan in ("rekomendasiin lagi dong", "ada yang lain ga"):
        _, lanjut = chat(pesan, {"tipe_kulit": "sensitif", "masalah_kulit": ["kemerahan_iritasi", "dehidrasi"],
                                 "budget": 50000}, konteks)
        konteks = lanjut["konteks"]
        budget_berikutnya.append(konteks["profil"]["budget_max"])
    cek("1.10", "Ganti budget saja lewat chat -> cuma budget yang berubah & STICKY di pesan-pesan berikutnya",
        p1["budget_max"] == 100000 and p1["tipe_kulit"] == p0["tipe_kulit"] == "sensitif"
        and p1["masalah_kulit"] == p0["masalah_kulit"] and naik["recommendation"] and harga_ok
        and budget_berikutnya == [100000, 100000],
        f"sebelum={p0}, sesudah={p1}, semua harga <= 100rb={harga_ok}, "
        f"budget di 2 pesan berikutnya (form tetap kirim 50rb)={budget_berikutnya}")

    # 1.11 user login: isi form sekali -> kunjungan berikutnya langsung ke chat pakai profil terakhir
    import sqlite3
    email, sandi = "uji.skenario.1_11@example.com", "rahasia123"
    requests.post(f"{BACKEND_URL}/register", json={"nama": "Uji 1.11", "email": email, "password": sandi})
    try:
        kunjungan = []
        for isi_form in (True, False):  # kunjungan pertama isi form, kunjungan kedua (sesi baru) tidak
            at = _app_onboarding()
            at.query_params["ke"] = "login"
            at.run()
            at.text_input[0].set_value(email)
            at.text_input[1].set_value(sandi)
            at.button[0].click()
            at.run()
            langsung_chat = at.session_state["onboarding_selesai"] and len(at.chat_input) == 1
            if isi_form:
                _isi_form(at, "kombinasi", ["jerawat", "kusam", "penuaan"], None, tanpa_batas=True)
            kunjungan.append((langsung_chat, dict(at.session_state["onboarding"]), at.session_state["onboarding_selesai"]))
        (chat_1, _, selesai_1), (chat_2, ob_2, _) = kunjungan
        cek("1.11", "User login isi form sekali -> kunjungan berikutnya langsung chat pakai profil terakhir",
            not chat_1 and selesai_1 and chat_2 and ob_2["tipe_kulit"] == "kombinasi"
            and ob_2["masalah_kulit"] == ["jerawat", "kusam", "penuaan"] and ob_2["tanpa_batas_budget"],
            f"kunjungan 1: langsung chat={chat_1} (akun baru -> isi form dulu), form tersimpan={selesai_1}; "
            f"kunjungan 2: langsung chat={chat_2}, profil dipulihkan={ob_2}")
    finally:
        conn = sqlite3.connect(ROOT / "backend" / "chatbot.db")
        uid = conn.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()
        if uid:
            conn.execute("DELETE FROM messages WHERE conversation_id IN (SELECT id FROM conversations WHERE user_id=?)", uid)
            conn.execute("DELETE FROM conversations WHERE user_id=?", uid)
            conn.execute("DELETE FROM users WHERE id=?", uid)
            conn.commit()
        conn.close()

    # 1.12 tamu, kunjungan baru -> form wajib diisi ulang + ada penjelasan kenapa
    at = _app_onboarding()
    teks_halaman = " ".join(m.value for m in at.markdown)
    cek("1.12", "Tamu di kunjungan baru -> form diisi ulang dari awal + ada penjelasan profil tamu tidak disimpan",
        not at.session_state["onboarding_selesai"] and len(at.chat_input) == 0 and len(at.selectbox) == 1
        and "won't be saved" in teks_halaman and ">Login</a>" in teks_halaman,
        "form tampil, chat belum bisa dipakai; pesan: "
        + next((m.value for m in at.markdown if "won't be saved" in m.value), "(tidak ada)"))


# ---------------- BAGIAN 2: jumlah produk ----------------

def _ids(data):
    return [x["id"] for x in data.get("recommendation", [])]


def uji_bagian_2():
    print("\n=== BAGIAN 2: Jumlah produk yang diminta ===")
    import pandas as pd
    katalog = pd.read_csv(ROOT / "data" / "products_final.csv").set_index("id")

    def jumlah(pesan, ob=None, konteks=None):
        _, d = chat(pesan, ob, konteks)
        return len(d.get("recommendation", [])), d

    hasil = {p: jumlah(p)[0] for p in ("kasih 1 aja", "rekomendasiin 1 produk", "satu aja cukup")}
    cek("2.1", "Minta 1 produk -> cuma 1 produk muncul", all(n == 1 for n in hasil.values()), f"jumlah tampil: {hasil}")

    hasil = {p: jumlah(p)[0] for p in ("kasih 3 produk", "3 aja")}
    cek("2.2", "Minta 3 produk -> 3 produk", all(n == 3 for n in hasil.values()), f"jumlah tampil: {hasil}")

    hasil = {p: jumlah(p) for p in ("kasih semua yang cocok", "banyakin dong", "kasih 20", "kasih 50 produk")}
    n = {p: v[0] for p, v in hasil.items()}
    cek("2.3", "Minta jumlah besar -> angka eksplisit dipakai, 'semua'/'banyak' pakai batas wajar (bukan 984)",
        n["kasih 20"] == 20 and 15 <= n["kasih semua yang cocok"] <= 20 and n["banyakin dong"] > 3
        and n["kasih 50 produk"] == 20 and "paling cocok" in hasil["kasih semua yang cocok"][1]["explanation"]
        and "Maksimal 20" in hasil["kasih 50 produk"][1]["explanation"],
        f"jumlah tampil: {n}")

    n, d = jumlah("rekomendasiin dong")
    cek("2.4", "Tidak sebut jumlah -> default 3 + dikasih tau bisa minta lebih banyak/sedikit",
        n == 3 and "kasih 5" in d["explanation"], f"jumlah tampil={n}; penjelasan: {d['explanation'][-95:]!r}")

    ob = {"tipe_kulit": "berminyak", "masalah_kulit": ["kemerahan_iritasi"], "budget": 10000}
    n, d = jumlah("kasih 10", ob)
    relevan = all(("kemerahan_iritasi" in str(katalog.at[i, "masalah_kulit_cocok"]))
                  or pd.isna(katalog.at[i, "masalah_kulit_cocok"]) for i in _ids(d))
    murah = all(x["harga"] <= 10000 for x in d["recommendation"])
    cek("2.5", "Minta 10 tapi yang cocok cuma sedikit -> tampilkan yang ada + bilang 'cuma ketemu N', tanpa produk asal",
        0 < n < 10 and f"Cuma ketemu **{n} produk**" in d["explanation"] and relevan and murah,
        f"minta 10 -> tampil {n}, semua menangani kemerahan/iritasi={relevan}, semua <= 10rb={murah}; "
        f"penjelasan: {d['explanation'][-120:]!r}")

    hasil = {p: chat(p) for p in ("kasih 0 produk", "-5 produk")}
    cek("2.6", "Jumlah 0 / negatif -> tidak crash, minta klarifikasi",
        all(s == 200 and d["tipe"] == "klarifikasi" and not d["recommendation"] for s, d in hasil.values()),
        "; ".join(f"{p!r} -> {s}, {d['explanation']!r}" for p, (s, d) in hasil.items()))

    hasil = {p: jumlah(p)[0] for p in ("kasih beberapa aja", "sedikit aja", "banyakin")}
    cek("2.7", "Jumlah dalam kata -> 'beberapa'/'sedikit' kecil (bukan default 3), 'banyakin' > default",
        hasil["kasih beberapa aja"] == 2 and hasil["sedikit aja"] == 2 and hasil["banyakin"] > 3,
        f"jumlah tampil: {hasil}")

    _, awal = chat("rekomendasiin dong")
    _, dua = chat("kebanyakan, 2 aja deh", konteks=awal["konteks"])
    _, banyak = chat("banyakin dong", konteks=dua["konteks"])
    alasan_sama = [x["alasan"] for x in dua["recommendation"]] == [x["alasan"] for x in awal["recommendation"][:2]]
    cek("2.8", "Ganti jumlah setelah rekomendasi -> dipotong/ditambah dari hasil yang SAMA, bukan cari ulang",
        _ids(dua) == _ids(awal)[:2] and alasan_sama and _ids(banyak)[:3] == _ids(awal) and len(banyak["recommendation"]) > 3,
        f"awal={_ids(awal)}, '2 aja deh'={_ids(dua)} (alasan sama persis={alasan_sama}), "
        f"'banyakin dong' -> {len(banyak['recommendation'])} produk, 3 pertama={_ids(banyak)[:3]}")

    from itertools import combinations

    def skor_akhir(d):
        return [int(v.split("/")[0]) for v in d["perbandingan"]["baris"][-1]["nilai"]]
    frasa = ("jadi finalnya yg bagusan mana?", "yang paling oke yang mana", "pilih satu yang terbaik", "worth dibeli yang mana")
    hasil = {p: chat(p, konteks=awal["konteks"])[1] for p in frasa}
    daftar = _ids(awal)
    benar = {p: len(d["recommendation"]) == 1 and d["perbandingan"]["baris"][-1]["atribut"] == "Skor akhir"
             and len(skor_akhir(d)) == len(daftar)
             and d["recommendation"][0]["id"] == daftar[skor_akhir(d).index(max(skor_akhir(d)))]
             and "Alasannya:" in d["explanation"] and "Cara hitung skor" in d["explanation"]
             and d["konteks"]["pool"] == awal["konteks"]["pool"]
             for p, d in hasil.items()}
    _, sepuluh = chat("kasih 10")
    tipis = None
    for i, j in combinations(range(len(_ids(sepuluh))), 2):
        _, d = chat(f"yang bagusan nomor {i + 1} atau nomor {j + 1}?", konteks=sepuluh["konteks"])
        if "selisihnya tipis" in d["explanation"]:
            tipis = (i + 1, j + 1, skor_akhir(d), d["explanation"])
            break
    contoh = hasil[frasa[0]]
    cek("2.9", "'yang bagusan mana' dkk -> sempit ke 1 pemenang dari hasil yang SAMA, dipilih dari rincian skor "
               "(bukan otomatis nomor 1); skor tipis -> dijelaskan trade-off-nya",
        all(benar.values()) and tipis is not None and "unggul karena" in tipis[3],
        f"daftar={daftar}; skor akhir={skor_akhir(contoh)} -> pemenang {_ids(contoh)} "
        f"(nomor {daftar.index(_ids(contoh)[0]) + 1}); tiap frasa benar={benar}; "
        + (f"trade-off nomor {tipis[0]} vs {tipis[1]} skor {tipis[2]}: "
           f"{[s for s in tipis[3].split(chr(10)) if 'tipis' in s]}" if tipis else "trade-off: tidak ketemu pasangan tipis"))


# ---------------- BAGIAN 3: filter kategori ----------------

def _kategori(data):
    return [x["kategori"] for x in data.get("recommendation", [])]


def uji_bagian_3():
    print("\n=== BAGIAN 3: Filter kategori dari chat ===")
    import pandas as pd
    katalog = pd.read_csv(ROOT / "data" / "products_final.csv").set_index("id")

    def _cocok(tag, nilai):
        return pd.isna(tag) or nilai in [t.strip() for t in str(tag).split(";")]

    harapan = {"carikan facewash aja": "facial_wash", "sunscreen dong": "sunscreen", "mau serum": "serum",
               "sunblock dong": "sunscreen", "carikan obat totol jerawat": "acne_gel"}
    ob_berminyak = {"tipe_kulit": "berminyak", "masalah_kulit": ["jerawat"], "budget": 150000}
    # acne gel (obat totol jerawat) = kategori baru hasil review data; dicek dengan profil berminyak
    # karena belum ada acne gel untuk kulit kering yang masuk budget 150rb
    hasil = {p: chat(p, ob_berminyak if harapan[p] == "acne_gel" else None)[1] for p in harapan}
    cek("3.1", "Kategori disebut (termasuk sinonim facewash/sunblock/obat totol) -> hasil cuma kategori itu",
        all(d["recommendation"] and set(_kategori(d)) == {harapan[p]} and d["konteks"]["kategori"] == [harapan[p]]
            for p, d in hasil.items()),
        "; ".join(f"{p!r} -> {sorted(set(_kategori(d)), key=str)}" for p, d in hasil.items()))

    ob = {"tipe_kulit": "normal", "masalah_kulit": ["kusam"], "budget": 200000}
    _, d = chat("carikan sunscreen buat kulit berminyak yang jerawatan", ob)
    k = d["konteks"]
    semua_cocok = all(_cocok(katalog.at[i, "tipe_kulit_cocok"], "berminyak")
                      and _cocok(katalog.at[i, "masalah_kulit_cocok"], "jerawat") for i in _ids(d))
    cek("3.2", "Kategori + tipe kulit + masalah kulit sekaligus -> semua filter aktif bersamaan",
        k["kategori"] == ["sunscreen"] and k["profil"]["tipe_kulit"] == "berminyak"
        and k["profil"]["masalah_kulit"] == ["jerawat"] and set(_kategori(d)) == {"sunscreen"} and semua_cocok,
        f"filter={k['kategori']}, tipe={k['profil']['tipe_kulit']}, masalah={k['profil']['masalah_kulit']}, "
        f"hasil={sorted(set(_kategori(d)), key=str)}, semua cocok berminyak & jerawat={semua_cocok}")

    _, tidak = chat("carikan actives aja")
    _, typo = chat("essense dong")
    cek("3.3", "Kategori tidak dikenal -> bilang terus terang (tanpa produk sembarang); typo -> dikenali",
        tidak["tipe"] == "klarifikasi" and not tidak["recommendation"] and "nggak ada di data" in tidak["explanation"]
        and "sunscreen" in tidak["explanation"] and tidak["konteks"]["kategori"] == []
        and typo["konteks"]["kategori"] == ["essence"] and set(_kategori(typo)) <= {"essence"}
        and (typo["recommendation"] or "essence" in typo["explanation"]),
        f"'actives' -> {tidak['explanation']!r}; 'essense' -> filter={typo['konteks']['kategori']}, "
        f"{len(typo['recommendation'])} produk {sorted(set(_kategori(typo)), key=str)}")

    _, serum = chat("mau serum")
    _, toner = chat("kalau toner ada rekomendasi apa?", konteks=serum["konteks"])
    _, lagi = chat("rekomendasiin lagi dong", konteks=toner["konteks"])
    cek("3.4", "Ganti kategori di tengah chat -> kategori baru STICKY, filter lain tetap",
        set(_kategori(serum)) == {"serum"} and set(_kategori(toner)) == {"toner"} and set(_kategori(lagi)) == {"toner"}
        and toner["konteks"]["profil"] == serum["konteks"]["profil"] == lagi["konteks"]["profil"]
        and "Masih pakai filter kategori" in lagi["explanation"],
        f"serum -> {sorted(set(_kategori(serum)), key=str)}, 'kalau toner...' -> {sorted(set(_kategori(toner)), key=str)}, "
        f"pesan berikutnya -> {sorted(set(_kategori(lagi)), key=str)}; profil sama={toner['konteks']['profil'] == serum['konteks']['profil']}")

    _, awal = chat("rekomendasiin dong")
    _, reset = chat("semua kategori aja", konteks=lagi["konteks"])
    cek("3.5", "Tidak sebut kategori di awal -> semua kategori; 'semua kategori' melepas filter yang sticky",
        awal["konteks"]["kategori"] == [] and awal["recommendation"]
        and reset["konteks"]["kategori"] == [] and reset["recommendation"],
        f"awal filter={awal['konteks']['kategori']} ({sorted(set(_kategori(awal)), key=str)}); "
        f"'semua kategori aja' -> filter={reset['konteks']['kategori']} ({sorted(set(_kategori(reset)), key=str)})")

    _, atau = chat("serum atau toner aja")
    _, pasang = chat("kasih 2 serum sama 2 toner")

    def _ringkas(d):
        return [(g["judul"], len(g["produk"]), sorted({x["kategori"] for x in g["produk"]})) for g in (d["grup"] or [])]

    def _grup_ok(d, diminta):
        # tiap kelompok berisi kategorinya sendiri; kalau kurang dari yang diminta
        # (produk cocoknya memang sedikit, lihat 2.5) bot wajib bilang
        grup = _ringkas(d)
        return [g[0] for g in grup] == ["Serum", "Toner"] and all(
            g[2] == [g[0].lower()] and (g[1] == diminta or (0 < g[1] < diminta and
                                                           f"{g[0]}: cuma ketemu **{g[1]} produk**" in d["explanation"]))
            for g in grup)
    cek("3.6", "2 kategori sekaligus -> tampil 2 kelompok terpisah (bukan diam-diam cuma salah satu)",
        _grup_ok(atau, 3) and _grup_ok(pasang, 2),
        f"'serum atau toner aja' -> {_ringkas(atau)}; 'kasih 2 serum sama 2 toner' -> {_ringkas(pasang)}; "
        f"catatan: {[s for s in atau['explanation'].split(chr(10)) if 'cuma ketemu' in s]}")


# ---------------- BAGIAN 4: perbandingan produk ----------------

def uji_bagian_4():
    print("\n=== BAGIAN 4: Perbandingan produk ===")
    import pandas as pd
    katalog = pd.read_csv(ROOT / "data" / "products_final.csv").set_index("id")

    def kolom(d):
        return d["konteks"]["banding"] if d.get("perbandingan") else []

    def baris(d):
        return [b["atribut"] for b in (d.get("perbandingan") or {}).get("baris", [])]

    _, d = chat("bandingkan hada labo gokujyun face wash dengan cetaphil gentle skin cleanser")
    nama = [katalog.at[i, "nama_produk"] for i in kolom(d)]
    cek("4.1", "Bandingkan 2 produk pakai nama -> ketemu di database, tabel berdampingan + kesimpulan",
        len(nama) == 2 and "hada labo gokujyun" in nama[0].lower() and "cetaphil gentle skin cleanser" in nama[1].lower()
        and "Harga" in baris(d) and "Kesimpulan" in d["explanation"] and "paling murah" in d["explanation"]
        and "Paling sesuai dengan profil kamu" in d["explanation"],
        f"ketemu={nama}; baris tabel={baris(d)}; kesimpulan={d['explanation'][:230]!r}")

    # 4.1b (temuan uji manual): 2 nama produk LENGKAP + "bagusan mana", TANPA kata "bandingkan"
    def nama_lengkap(potongan):
        return next(n for n in katalog["nama_produk"] if potongan in n.lower())
    a_nama = nama_lengkap("hiqween healty glow finished sunscreen")
    b_nama = nama_lengkap("azarine hydrashoothe sunscreen gel 45")
    _, awal_b = chat("rekomendasiin sunscreen dong")
    kalimat = f"dari produk {a_nama} dengan produk {b_nama}, bagusan yg mana"
    _, d1b = chat(kalimat, konteks=awal_b["konteks"])
    _, d1b_baru = chat(kalimat)
    _, d1b_mending = chat(f"mending {a_nama} atau {b_nama}?")
    _, d1b_eksplisit = chat(f"bandingkan {a_nama} dengan {b_nama}")
    _, d1b_29 = chat("yang bagusan mana?", konteks=awal_b["konteks"])
    nama1b = [katalog.at[i, "nama_produk"] for i in kolom(d1b)]
    cek("4.1b", "2 nama produk lengkap + 'bagusan mana' TANPA kata 'bandingkan' -> tabel perbandingan 2 produk "
                "yang disebut (bukan rekomendasi baru); 'bagusan mana' TANPA nama tetap pilih 1 dari daftar (2.9)",
        d1b["tipe"] == "perbandingan" and nama1b == [a_nama, b_nama] and d1b["recommendation"] == []
        and d1b["konteks"]["tampil"] == awal_b["konteks"]["tampil"]
        and "Paling sesuai dengan profil kamu" in d1b["explanation"]
        and kolom(d1b) == kolom(d1b_baru) == kolom(d1b_mending) == kolom(d1b_eksplisit)
        and d1b_29["tipe"] == "pilih_satu",
        f"'{kalimat[:70]}...' -> {d1b['tipe']}, kolom={nama1b}, kartu rekomendasi baru={len(d1b['recommendation'])}, "
        f"daftar sebelumnya tetap={d1b['konteks']['tampil'] == awal_b['konteks']['tampil']}; tanpa daftar sebelumnya, "
        f"'mending A atau B?', dan 'bandingkan A dengan B' -> kolom sama="
        f"{kolom(d1b) == kolom(d1b_baru) == kolom(d1b_mending) == kolom(d1b_eksplisit)}; "
        f"'yang bagusan mana?' tanpa nama -> {d1b_29['tipe']}")

    _, awal = chat("rekomendasiin dong")
    _, d2 = chat("bandingkan nomor 1 sama nomor 3", konteks=awal["konteks"])
    tampil = awal["konteks"]["tampil"]
    cek("4.2", "Bandingkan pakai nomor urut dari rekomendasi sebelumnya -> produk nomor 1 & 3 yang tadi",
        kolom(d2) == [tampil[0], tampil[2]] and d2["konteks"]["tampil"] == tampil,
        f"daftar tadi={tampil}; dibandingkan={kolom(d2)}; label kolom={d2['perbandingan']['produk']}")

    _, d3 = chat("bandingkan 1, 2, sama 3", konteks=awal["konteks"])
    cek("4.3", "Bandingkan lebih dari 2 produk -> tabel 3 kolom",
        kolom(d3) == tampil[:3] and len(d3["perbandingan"]["produk"]) == 3,
        f"kolom={d3['perbandingan']['produk']}")

    _, d4 = chat("bandingkan glowy magic serum xyz dengan cetaphil gentle skin cleanser")
    _, d4b = chat("bandingkan wardah sama azarine")
    cek("4.4", "Nama produk tidak ada di database -> bilang terus terang, tanpa tabel/data karangan "
               "(nama terlalu umum -> tanya balik)",
        not d4.get("perbandingan") and "\"glowy magic serum xyz\" nggak ketemu" in d4["explanation"]
        and not d4b.get("perbandingan") and "Maksud kamu yang mana?" in d4b["explanation"],
        f"{d4['explanation']!r}; 'wardah sama azarine' -> {d4b['explanation'][:160]!r}")

    _, d5 = chat("bandingkan azarine hydrasoothe dengan wardah lightening face mist")
    nama5 = [katalog.at[i, "nama_produk"] for i in kolom(d5)]
    cek("4.5", "Produk yang belum pernah direkomendasikan -> tetap dicari di seluruh database",
        len(nama5) == 2 and "hydrasoothe" in nama5[0].lower() and "wardah lightening face mist" in nama5[1].lower(),
        f"percakapan baru (belum ada rekomendasi) -> ketemu {nama5}")

    fokus = {}
    for pesan, harap in (("yang mana yang lebih murah?", ["Harga"]), ("yang ratingnya lebih bagus yang mana?", ["Rating", "Ulasan"]),
                         ("kandungannya beda apa?", ["Kandungan"])):
        _, d6 = chat(pesan, konteks=d3["konteks"])
        fokus[pesan] = (baris(d6), harap, d6["explanation"])
    harga = {i: katalog.at[i, "harga"] for i in tampil[:3]}
    termurah = katalog.at[min(harga, key=harga.get), "nama_produk"][:20]
    cek("4.6", "Tanya atribut spesifik -> jawaban fokus ke atribut itu, bukan tabel lengkap",
        all(b == h for b, h, _ in fokus.values()) and termurah in fokus["yang mana yang lebih murah?"][2],
        "; ".join(f"{p!r} -> baris {b}" for p, (b, _, _) in fokus.items())
        + f"; jawaban termurah: {fokus['yang mana yang lebih murah?'][2]!r}")

    _, pakai_partikel = chat("perbandingan donk antara wardah dan skin 1004")
    _, tanpa_partikel = chat("perbandingan antara wardah dan skin 1004")
    _, variasi = chat("bandingin dongg skin 1004 madagascar centella tone brightening sama cetaphil gentle skin cleanser dehh")
    _, rapat = chat("bandingkan skin1004 madagascar centella tone brightening dengan cetaphil gentle skin cleanser")
    nama_b = [katalog.at[i, "nama_produk"] for i in kolom(variasi)]
    cek("4b", "Produk yang ADA di data tidak boleh dibilang 'tidak ketemu': partikel (donk/dongg/dehh) dibuang, "
              "'skin 1004' = 'SKIN1004'",
        "nggak ketemu" not in pakai_partikel["explanation"] and "donk" not in pakai_partikel["explanation"]
        and pakai_partikel["explanation"] == tanpa_partikel["explanation"]
        and "cocok dengan \"wardah\"" in pakai_partikel["explanation"]
        and "cocok dengan \"skin 1004\"" in pakai_partikel["explanation"]
        and len(nama_b) == 2 and nama_b[0].upper().startswith("SKIN1004") and "cetaphil" in nama_b[1].lower()
        and kolom(rapat) == kolom(variasi),
        f"'donk' vs tanpa 'donk' -> jawaban identik={pakai_partikel['explanation'] == tanpa_partikel['explanation']}, "
        f"'skin 1004' ketemu (brand saja -> tanya balik kandidat); 'skin 1004 madagascar…' & 'skin1004 madagascar…' -> "
        f"{nama_b} (sama={kolom(rapat) == kolom(variasi)})")

    kosong = katalog[katalog["tipe_kulit_cocok"].isna() & katalog["kandungan"].isna()].iloc[0]
    _, d7 = chat(f"bandingkan {kosong['nama_produk']} dengan cetaphil gentle skin cleanser")
    tabel = d7.get("perbandingan") or {"baris": []}
    sel = {b["atribut"]: b["nilai"][0] for b in tabel["baris"]}
    mentah = [v for b in tabel["baris"] for v in b["nilai"] if str(v).strip().lower() in ("nan", "none", "")]
    cek("4.7", "Produk dengan data kosong -> 'tidak ada data' eksplisit, bukan kosong/nan/None",
        sel.get("Cocok untuk kulit") == "tidak ada data" and sel.get("Kandungan") == "tidak ada data" and not mentah,
        f"{kosong['nama_produk']!r}: cocok untuk kulit={sel.get('Cocok untuk kulit')!r}, kandungan={sel.get('Kandungan')!r}")


# ---------------- BAGIAN 5: budget ----------------

def _harga(d):
    return [x["harga"] for x in d.get("recommendation", [])]


def uji_bagian_5():
    print("\n=== BAGIAN 5: Budget ===")

    ob = {"tipe_kulit": "kering", "masalah_kulit": ["jerawat"], "budget": 500}
    _, d = chat("rekomendasiin dong", ob)
    harga = _harga(d)
    cek("5.1", "Budget di bawah produk termurah yang cocok -> bilang terus terang + tawarkan alternatif "
               "(yang termurah, ditandai di luar budget), budget user tidak diubah diam-diam",
        d["tipe"] == "di_luar_budget" and harga and all(h > 500 for h in harga) and harga == sorted(harga)
        and all(x["di_luar_budget"] for x in d["recommendation"]) and "di luar budget kamu" in d["explanation"]
        and "naikin budget" in d["explanation"] and d["konteks"]["profil"]["budget_max"] == 500,
        f"budget Rp500 (di bawah produk termurah se-katalog, Rp621) -> {len(harga)} alternatif termurah {harga} (semua ditandai di luar budget); "
        f"budget tetap={d['konteks']['profil']['budget_max']}; penjelasan: {d['explanation'][:230]!r}")

    ob = {"tipe_kulit": "sensitif", "masalah_kulit": ["kemerahan_iritasi"], "budget": 50000}
    _, serum = chat("mau serum", ob)
    _, naik = chat("kalau budgetnya dinaikin ke 100rb gimana?", ob, serum["konteks"])
    p0, p1 = serum["konteks"], naik["konteks"]
    cek("5.2", "Ganti budget di tengah chat -> cuma budget yang berubah, filter lain (kategori, profil) tetap, hasil baru",
        p1["profil"]["budget_max"] == 100000 and p1["kategori"] == p0["kategori"] == ["serum"]
        and p1["profil"]["tipe_kulit"] == p0["profil"]["tipe_kulit"] and p1["profil"]["masalah_kulit"] == p0["profil"]["masalah_kulit"]
        and naik["recommendation"] and all(h <= 100000 for h in _harga(naik)) and set(_kategori(naik)) == {"serum"}
        and "Budget aku ubah" in naik["explanation"],
        f"sebelum: budget={p0['profil']['budget_max']}, kategori={p0['kategori']}; sesudah: budget={p1['profil']['budget_max']}, "
        f"kategori={p1['kategori']}, harga={_harga(naik)}")

    _, d = chat("carikan 3 serum di bawah 150rb buat kulit kering", {"tipe_kulit": "normal", "masalah_kulit": ["kusam"],
                                                                     "budget": 200000})
    k = d["konteks"]
    n = len(d["recommendation"])
    cek("5.3", "Budget + kategori + jumlah + tipe kulit dalam 1 kalimat -> semua aktif bersamaan",
        k["profil"]["budget_max"] == 150000 and k["kategori"] == ["serum"] and k["profil"]["tipe_kulit"] == "kering"
        and (n == 3 or (0 < n < 3 and "Cuma ketemu" in d["explanation"]))
        and set(_kategori(d)) == {"serum"} and all(h <= 150000 for h in _harga(d)),
        f"jumlah tampil={n}, kategori={sorted(set(_kategori(d)), key=str)}, harga={_harga(d)}, "
        f"budget={k['profil']['budget_max']}, tipe={k['profil']['tipe_kulit']}")

    ob = {"tipe_kulit": "kombinasi", "masalah_kulit": ["jerawat", "kusam"], "budget": 100000}
    konteks, jejak = None, []
    for pesan in ("rekomendasiin dong", "sunscreen dong", "kalau toner ada?", "kasih 5", "semua kategori aja",
                  "bandingkan 1 sama 2", "rekomendasiin lagi dong"):
        _, d = chat(pesan, ob, konteks)
        konteks = d["konteks"]
        jejak.append((pesan, konteks["profil"]["budget_max"], max(_harga(d) or [0])))
    cek("5.4", "Budget dari form dipakai konsisten di semua pesan berikutnya tanpa disebut ulang",
        all(b == 100000 and h <= 100000 for _, b, h in jejak),
        "; ".join(f"{p!r}: budget={b}, harga tertinggi tampil={h:,.0f}" for p, b, h in jejak))


# ---------------- BAGIAN 6: percakapan lanjutan (follow-up) ----------------

def _kutipan(teks):
    """Kutipan ulasan di jawaban bot, dikelompokkan per judul bagian
    ("Yang bilang bagus:" / "Yang kurang puas:" / ...): [(judul, isi, bintang)]."""
    import re
    hasil, judul = [], None
    for baris in teks.splitlines():
        if baris.endswith(":") and not baris.startswith(">"):
            judul = baris
        m = re.match(r'> "(.*)"(?: \(★ (\d)\))?$', baris)
        if m:
            hasil.append((judul, m.group(1), int(m.group(2)) if m.group(2) else None))
    return hasil


def _kutipan_asli(isi, ulasan_produk):
    """Setiap potongan kutipan (dipisah " · ", label "Tekstur: " dibuang,
    "…" di ujung dibuang) harus benar-benar ada di ulasan asli produk itu."""
    import re
    norm = lambda s: re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()  # noqa: E731
    gabungan = " || ".join(norm(u) for u in ulasan_produk)
    for bagian in isi.rstrip("…").split(" · "):
        bagian = re.sub(r"^[A-Z][a-z]+(?: [a-z]+)?: ", "", bagian)
        if norm(bagian)[:80] not in gabungan:
            return False
    return True


def uji_bagian_6():
    print("\n=== BAGIAN 6: Percakapan lanjutan (follow-up) ===")
    import pandas as pd
    katalog = pd.read_csv(ROOT / "data" / "products_final.csv")
    link = dict(zip(katalog["id"], katalog["link"]))
    ob = {"tipe_kulit": "berminyak", "masalah_kulit": ["jerawat"], "budget": 150000}

    # 6.1 alasan rekomendasi -> dari data tag produk vs profil, bukan generik
    _, kosong = chat("kenapa produk ini direkomendasiin?", ob)
    _, awal = chat("rekomendasiin sunscreen dong", ob)
    _, semua = chat("kenapa produk ini direkomendasiin?", ob, awal["konteks"])
    _, satu = chat("kenapa nomor 2 direkomendasiin?", ob, awal["konteks"])
    t, t2 = semua["explanation"], satu["explanation"]
    n = len(awal["recommendation"])
    per_produk = all(f"**#{i} " in t for i in range(1, n + 1))
    rinci = all(x in t for x in ("Tipe kulit:", "Masalah kulit:", "Kategori:", "Harga:", "Ulasan:", "(data produk:",
                                 "berminyak", "jerawat", "sunscreen"))
    cek("6.1", "Tanya alasan -> dijelaskan per produk dari tipe_kulit_cocok/masalah_kulit_cocok/kategori vs profil "
               "(\"produk ini\" = semua yang tampil, \"nomor 2\" = nomor 2 saja)",
        semua["tipe"] == "alasan" and per_produk and rinci and not semua["recommendation"]
        and semua["konteks"]["tampil"] == awal["konteks"]["tampil"]
        and satu["tipe"] == "alasan" and "**#2 " in t2 and "**#1 " not in t2 and "**#3 " not in t2
        and kosong["tipe"] == "klarifikasi" and not kosong["recommendation"],
        f"{n} produk dijelaskan satu per satu={per_produk}, memuat tag & profil={rinci}; 'nomor 2' -> cuma #2; "
        f"tanpa rekomendasi sebelumnya -> {kosong['explanation'][:70]!r}; contoh: "
        f"{t2[t2.index('**#2'):][:260]!r}")

    # 6.2 "yang lain dong" -> produk yang SUDAH tampil tidak muncul lagi
    _, lain1 = chat("yang lain dong, selain ini", ob, awal["konteks"])
    _, lain2 = chat("yang lain lagi dong", ob, lain1["konteks"])
    a0, a1, a2 = set(_ids(awal)), set(_ids(lain1)), set(_ids(lain2))
    ob_sempit = {"tipe_kulit": "kering", "masalah_kulit": ["penuaan"], "budget": 30000}
    _, d = chat("carikan eye cream", ob_sempit)
    dilihat, dobel, putaran = set(_ids(d)), False, 0
    while d["tipe"] == "rekomendasi" and putaran < 15:
        _, d = chat("yang lain lagi dong", ob_sempit, d["konteks"])
        dobel |= bool(set(_ids(d)) & dilihat)
        dilihat |= set(_ids(d))
        putaran += 1
    _, ulang = chat("yang lain lagi dong", ob_sempit, d["konteks"])
    cek("6.2", "Minta alternatif -> produk yang sudah ditampilkan dikeluarkan (jumlah sama, filter tetap); "
               "kalau sudah habis, bilang terus terang",
        len(a1) == len(a0) == len(a2) and not (a0 & a1) and not (a2 & (a0 | a1))
        and set(_kategori(lain1)) == set(_kategori(lain2)) == {"sunscreen"}
        and not dobel and d["tipe"] == "kosong" and "sudah aku tampilkan" in d["explanation"]
        and ulang["tipe"] == "kosong" and not ulang["recommendation"],
        f"daftar 1={len(a0)}, 'yang lain'={len(a1)} (irisan {len(a0 & a1)}), 'yang lain lagi'={len(a2)} "
        f"(irisan {len(a2 & (a0 | a1))}); profil sempit: {len(dilihat)} produk unik dalam {putaran} putaran tanpa "
        f"dobel, lalu -> {d['explanation'][:110]!r}")

    # 6.3 lebih murah -> budget_max diketatkan (sticky + diumumkan)
    termurah = min(h for h in _harga(awal) if h is not None)
    _, murah = chat("ada yang lebih murah?", ob, awal["konteks"])
    _, lanjut = chat("rekomendasiin lagi dong", ob, murah["konteks"])
    b = murah["konteks"]["profil"]["budget_max"]
    d, putaran = murah, 0
    while d["tipe"] == "rekomendasi" and putaran < 15:
        sebelum = d["konteks"]["profil"]["budget_max"]
        _, d = chat("ada yang lebih murah?", ob, d["konteks"])
        putaran += 1
    cek("6.3", "Minta yang lebih murah -> budget_max diketatkan di bawah harga termurah hasil sebelumnya, "
               "diumumkan & sticky; kalau sudah paling murah, budget tidak diubah",
        murah["recommendation"] and all(h < termurah for h in _harga(murah)) and b == termurah - 1
        and "Budget aku ketatkan" in murah["explanation"]
        and lanjut["konteks"]["profil"]["budget_max"] == b and all(h < termurah for h in _harga(lanjut))
        and d["tipe"] == "kosong" and "paling murah" in d["explanation"]
        and d["konteks"]["profil"]["budget_max"] == sebelum,
        f"termurah tadi Rp{termurah:,.0f} -> budget_max={b}, harga baru={_harga(murah)}; pesan berikutnya "
        f"budget tetap {lanjut['konteks']['profil']['budget_max']}; setelah {putaran}x minta lebih murah -> "
        f"{d['explanation'][:120]!r}")

    # 6.4 ulasan -> kutipan ASLI dari RAG (dicek ke data ulasan mentah)
    ulasan = pd.read_csv(ROOT / "data" / "clean_merged_produk_ulasan_labelled_v2.csv", usecols=["link", "teks_bebas"])
    per_link = ulasan.dropna().groupby("link")["teks_bebas"].apply(list).to_dict()
    _, rev = chat("ada review bagus soal nomor 1 ga?", ob, awal["konteks"])
    _, kel = chat("keluhan orang soal nomor 2 apa aja?", ob, awal["konteks"])
    k1, k2 = _kutipan(rev["explanation"]), _kutipan(kel["explanation"])
    asli1 = all(_kutipan_asli(isi, per_link.get(link[awal["konteks"]["tampil"][0]], [])) for _, isi, _ in k1)
    asli2 = all(_kutipan_asli(isi, per_link.get(link[awal["konteks"]["tampil"][1]], [])) for _, isi, _ in k2)
    bagus = [x for x in k1 if x[0] == "Yang bilang bagus:"]
    keluhan_ok = all(bintang is None or bintang <= 3 for j, _, bintang in k2 if j == "Yang kurang puas:") and (
        any(j == "Yang kurang puas:" for j, _, _ in k2) or "Nggak ada ulasan negatif" in kel["explanation"])
    tanpa_ulasan = katalog[katalog["jml_ulasan"].fillna(0) == 0]
    nol = None
    for nama in tanpa_ulasan["nama_produk"].head(10):
        _, x = chat(f"review {nama} dong", ob)
        if x["tipe"] == "ulasan" and nama[:30] in x["explanation"]:
            nol = (nama, x)
            break
    _, ambigu = chat("review skintific dong", ob)
    cek("6.4", "Tanya ulasan -> kutipan ulasan asli dari RAG untuk produk itu (bukan dari CBF), keluhan -> ulasan "
               "negatif; produk tanpa ulasan & nama ambigu dijawab jujur",
        rev["tipe"] == "ulasan" and len(bagus) >= 2 and asli1 and "ulasan positif dari" in rev["explanation"]
        and kel["tipe"] == "ulasan" and asli2 and keluhan_ok
        and nol is not None and "Belum ada ulasan" in nol[1]["explanation"] and not _kutipan(nol[1]["explanation"])
        and ambigu["tipe"] == "klarifikasi" and "Maksud kamu yang mana" in ambigu["explanation"],
        f"nomor 1: {len(k1)} kutipan, semua ada di ulasan asli={asli1}, contoh={k1[0][1][:90] if k1 else None!r}; "
        f"keluhan nomor 2: {len(k2)} kutipan, asli={asli2}, bintang keluhan <=3/\"nggak ada\"={keluhan_ok}; "
        f"produk tanpa ulasan ({(nol or ('-',))[0][:35]!r}) -> 'Belum ada ulasan'; 'skintific' -> tanya yang mana")

    # 6.5 urutkan -> re-sort daftar yang SAMA
    _, lima = chat("kasih 10 sunscreen", ob)  # 10 agar rating & harganya bervariasi
    _, u1 = chat("urutin dari yang termurah", ob, lima["konteks"])
    _, u2 = chat("yang rating tertinggi duluan", ob, u1["konteks"])
    _, u3 = chat("urutin dari yang termahal", ob, u2["konteks"])
    _, u4 = chat("urutin dong", ob, u3["konteks"])

    def urut(nilai, turun=False):
        ada = [v for v in nilai if v is not None]
        return ada == sorted(ada, reverse=turun) and nilai[:len(ada)] == ada  # yang kosong di bawah
    rating = [x["rating"] for x in u2["recommendation"]]
    sama = set(_ids(lima)) == set(_ids(u1)) == set(_ids(u2)) == set(_ids(u3))
    cek("6.5", "Minta diurutkan -> hasil yang SAMA diurutkan ulang (bukan cari ulang), kriteria tidak jelas -> tanya",
        sama and len(_ids(lima)) == 10 and len(set(rating)) > 1 and urut(_harga(u1)) and urut(rating, turun=True) and urut(_harga(u3), turun=True)
        and u4["tipe"] == "klarifikasi" and [x["nomor"] for x in u1["recommendation"]] == list(range(1, 11)),
        f"produk sama={sama}; termurah: {_harga(u1)}; rating tertinggi: {rating}; termahal: {_harga(u3)}; "
        f"'urutin dong' -> {u4['explanation'][:60]!r}")

    # 6.6 sesi baru: login -> profil diingat; tamu -> form lagi; konteks chat lama tidak terbawa
    email, sandi = "uji.skenario.6_6@example.com", "rahasia123"
    requests.post(f"{BACKEND_URL}/register", json={"nama": "Uji 6.6", "email": email, "password": sandi})
    import sqlite3
    try:
        token = requests.post(f"{BACKEND_URL}/login", json={"email": email, "password": sandi}).json()["access_token"]
        profil = {"tipe_kulit": "sensitif", "masalah_kulit": ["kemerahan_iritasi", "dehidrasi"], "budget": 80000}
        requests.put(f"{BACKEND_URL}/profile", json=profil, headers={"Authorization": f"Bearer {token}"})
        user = requests.post(f"{BACKEND_URL}/login", json={"email": email, "password": sandi}).json()["user"]
        diingat = (user["tipe_kulit"], user["masalah_kulit"], user["budget"]) == \
            (profil["tipe_kulit"], profil["masalah_kulit"], profil["budget"])
    finally:
        conn = sqlite3.connect(ROOT / "backend" / "chatbot.db")
        uid = conn.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()
        if uid:
            conn.execute("DELETE FROM messages WHERE conversation_id IN (SELECT id FROM conversations WHERE user_id=?)", uid)
            conn.execute("DELETE FROM conversations WHERE user_id=?", uid)
            conn.execute("DELETE FROM users WHERE id=?", uid)
            conn.commit()
        conn.close()
    at = _app_onboarding()
    form_tamu = not at.session_state["onboarding_selesai"] and len(at.selectbox) == 1 and len(at.chat_input) == 0
    _, baru = chat("rekomendasiin sunscreen dong", ob, None)  # sesi baru = konteks kosong
    k = baru["konteks"]
    bersih = k["profil"]["budget_max"] == 150000 and k["sudah_tampil"] == _ids(baru)
    cek("6.6", "Sesi baru -> user login: profil terakhir diingat; tamu: form diisi ulang; perubahan di chat lama "
               "(budget diketatkan, produk yang sudah tampil) tidak terbawa",
        diingat and form_tamu and bersih,
        f"login ulang -> profil={user['tipe_kulit']}, {user['masalah_kulit']}, budget {user['budget']}; tamu -> form "
        f"tampil={form_tamu}; chat baru: budget kembali ke form ({k['profil']['budget_max']}, sebelumnya diketatkan "
        f"jadi {b}), riwayat produk cuma {len(k['sudah_tampil'])} produk dari sesi ini")


# ---------------- BAGIAN 7: error handling & input di luar cakupan ----------------

_KATA_ID = {"yang", "untuk", "dan", "kulit", "ini", "dengan", "dari", "cocok", "harga", "ulasan", "produk", "buat"}
_KATA_EN = {"the", "for", "your", "and", "with", "this", "skin", "is", "are", "that", "you", "it", "of"}


def _bahasa_indonesia(teks):
    kata = [w.lower() for w in __import__("re").findall(r"[A-Za-z]+", teks)]
    return sum(w in _KATA_ID for w in kata) > 2 * sum(w in _KATA_EN for w in kata)


def _mesin_lokal():
    """CBF + Percakapan asli di proses ini (bukan lewat backend yang sedang
    jalan) -- supaya LLM & RAG bisa sengaja dirusak untuk 7.8/7.9."""
    if str(ROOT / "models") not in sys.path:
        sys.path.insert(0, str(ROOT / "models"))
    from cbf_engine import CBFEngine
    return CBFEngine()


def uji_bagian_7():
    print("\n=== BAGIAN 7: Error handling & input di luar cakupan ===")
    ob = {"tipe_kulit": "kering", "masalah_kulit": ["jerawat"], "budget": 150000}
    _, awal = chat("rekomendasiin sunscreen dong", ob)

    # 7.1 kosong / tidak jelas -> klarifikasi sopan, konteks tetap
    hasil = {}
    for pesan in ("...", "😊😊", "   ", "hmm", "asdfgh", "?"):
        s, d = chat(pesan, ob, awal["konteks"])
        hasil[pesan] = (s, d["tipe"], len(d["recommendation"]), d["konteks"]["tampil"] == awal["konteks"]["tampil"])
    s_kosong, d_kosong = chat("", ob)
    s_panjang, d_panjang = chat("serum " * 500, ob)
    cek("7.1", "Input kosong/emoji/spasi/tidak jelas -> minta klarifikasi sopan (tanpa produk, tidak crash), "
               "daftar produk sebelumnya tetap diingat",
        all(s == 200 and t == "klarifikasi" and n == 0 and tetap for s, t, n, tetap in hasil.values())
        and s_kosong == 400 and "tidak boleh kosong" in d_kosong["detail"]
        and s_panjang == 400 and "terlalu panjang" in d_panjang["detail"],
        "; ".join(f"{p!r}: {s} {t}, produk={n}, daftar lama tetap={tetap}" for p, (s, t, n, tetap) in hasil.items())
        + f"; pesan \"\" -> {s_kosong} {d_kosong['detail']!r}; 3000 karakter -> {s_panjang}")

    # 7.2 di luar topik -> bilang terus terang + arahkan balik
    luar = {}
    for pesan in ("gimana cuaca hari ini?", "siapa presiden indonesia", "resep nasi goreng dong", "rekomendasi film dong",
                  "what's the weather today?"):
        _, d = chat(pesan, ob)
        luar[pesan] = (d["tipe"], len(d["recommendation"]), "di luar cakupan" in d["explanation"]
                       and "rekomendasiin sunscreen" in d["explanation"])
    _, sapa = chat("halo kak", ob)
    _, bisa = chat("kamu bisa apa aja?", ob)
    cek("7.2", "Pertanyaan di luar topik skincare -> bilang di luar cakupan + contoh pertanyaan yang bisa (tanpa "
               "produk asal); sapaan/\"bisa apa\" dijawab, bukan dikasih rekomendasi",
        all(t == "di_luar_topik" and n == 0 and ok for t, n, ok in luar.values())
        and sapa["tipe"] == "sapaan" and not sapa["recommendation"] and "kulit kering" in sapa["explanation"]
        and bisa["tipe"] == "bantuan" and "bandingkan nomor 1 sama 2" in bisa["explanation"],
        "; ".join(f"{p!r}: {t}, produk={n}" for p, (t, n, _) in luar.items())
        + f"; 'halo kak' -> {sapa['explanation'][:60]!r}")

    # 7.3 medis -> tidak ada saran medis, arahkan ke dokter
    medis = {}
    for pesan in ("obat jerawat resep dokter apa ya", "aku harus pakai retinol berapa persen buat kulitku",
                  "jerawatku meradang parah bernanah harus minum antibiotik apa", "skincare aman buat ibu hamil apa"):
        _, d = chat(pesan, ob)
        medis[pesan] = (d["tipe"], len(d["recommendation"]), "dokter kulit" in d["explanation"]
                        and "bukan pengganti konsultasi medis" in d["explanation"])
    _, lunak = chat("obat jerawat yang ampuh apa ya", ob)
    cek("7.3", "Pertanyaan medis (resep, dosis, % bahan aktif, kondisi parah, kehamilan) -> tanpa saran/produk, "
               "arahkan ke dokter kulit; 'obat jerawat' biasa -> produk umum + pengingat bukan obat",
        all(t == "medis" and n == 0 and ok for t, n, ok in medis.values())
        and lunak["recommendation"] and "bukan obat" in lunak["explanation"],
        "; ".join(f"{p[:30]!r}: {t}, produk={n}, ke dokter={ok}" for p, (t, n, ok) in medis.items())
        + f"; 'obat jerawat yang ampuh' -> {len(lunak['recommendation'])} produk + catatan bukan obat")

    # 7.4 0 hasil -> bilang terus terang + tawarkan pelonggaran yang masuk akal, tidak diam-diam
    ob_a = {"tipe_kulit": "kering", "masalah_kulit": ["penuaan"], "budget": 25000}
    _, a = chat("carikan face mist", ob_a)
    _, a_ikut = chat("semua kategori", ob_a, a["konteks"])
    ob_b = {"tipe_kulit": "kering", "masalah_kulit": ["penuaan"], "budget": 15000}
    _, b = chat("carikan eksfoliator", ob_b)
    import re
    saran = re.search(r'bilang "(budget \d+rb)"', b["explanation"])
    _, b_ikut = chat(saran.group(1), ob_b, b["konteks"]) if saran else (None, {"recommendation": []})
    teks_b = b["explanation"]
    cek("7.4", "Semua filter -> 0 hasil: bilang terus terang, tawarkan kriteria yang bisa dilonggarkan (budget dulu, "
               "lalu kategori) & sarannya benar-benar menghasilkan produk; filter user tidak diubah diam-diam",
        a["tipe"] == "kosong" and not a["recommendation"] and "semua kategori" in a["explanation"]
        and a["konteks"]["kategori"] == ["mist"] and a_ikut["recommendation"]
        and b["tipe"] == "di_luar_budget" and all(x["di_luar_budget"] for x in b["recommendation"])
        and "**Budget**" in teks_b and "**Kategori**" in teks_b and teks_b.index("**Budget**") < teks_b.index("**Kategori**")
        and b["konteks"]["profil"]["budget_max"] == 15000 and b["konteks"]["kategori"] == ["eksfoliator"]
        and b_ikut["recommendation"] and not any(x["di_luar_budget"] for x in b_ikut["recommendation"]),
        f"face mist (kering, penuaan, 25rb) -> {a['explanation'][:90]!r}... -> ikuti 'semua kategori' -> "
        f"{len(a_ikut['recommendation'])} produk; eksfoliator 15rb -> {len(b['recommendation'])} alternatif ditandai "
        f"di luar budget, opsi budget lalu kategori, budget tetap {b['konteks']['profil']['budget_max']} -> ikuti "
        f"'{saran.group(1) if saran else '-'}' -> {len(b_ikut['recommendation'])} produk")

    # 7.5 produk tidak ada di database -> tidak mengarang
    tidak_ada = {}
    for pesan in ("berapa harga glowy magic serum xyz?", "review glowy magic serum xyz dong",
                  "kenapa glowy magic serum xyz direkomendasiin?", "glowy magic serum xyz bagus ga?",
                  "bandingkan glowy magic serum xyz dengan cetaphil gentle skin cleanser"):
        _, d = chat(pesan, ob)
        t = d["explanation"]
        tidak_ada[pesan] = ("nggak ada di data" in t or "nggak ketemu di data" in t) and "Rp" not in t and "★" not in t \
            and not d["recommendation"] and not d["perbandingan"]
    _, ada = chat("wardah lightening face mist bagus ga?", ob)
    katalog = __import__("pandas").read_csv(ROOT / "data" / "products_final.csv")
    wardah = katalog[katalog["nama_produk"].str.startswith("Wardah Lightening Face Mist")].iloc[0]
    cek("7.5", "Produk yang tidak ada di database -> bilang terus terang tidak ada, tanpa data karangan (harga/"
               "rating/ulasan); produk yang ADA dijawab dari data",
        all(tidak_ada.values()) and ada["tipe"] == "info_produk"
        and f"Rp{wardah['harga']:,.0f}".replace(",", ".") in ada["explanation"],
        "; ".join(f"{p[:40]!r}: jujur tidak ada={ok}" for p, ok in tidak_ada.items())
        + f"; produk ada ('wardah lightening face mist bagus ga?') -> harga Rp{wardah['harga']:,.0f} sesuai data")

    # 7.6 bahasa Inggris / campur -> dikenali, jawaban tetap bahasa Indonesia
    _, en = chat("give me 3 sunscreen recommendations for oily skin", ob)
    _, en2 = chat("recommend a moisturizer for dry skin between 50k and 100k", ob)
    _, en3 = chat("why is number 1 recommended?", ob, en["konteks"])
    k1, k2 = en["konteks"], en2["konteks"]
    indo = _bahasa_indonesia(en["explanation"]) and all(_bahasa_indonesia(x["alasan"]) for x in en["recommendation"])
    cek("7.6", "Pesan bahasa Inggris/campur -> maksudnya dikenali (kategori, tipe kulit, jumlah, budget, follow-up), "
               "jawaban tetap bahasa Indonesia",
        len(en["recommendation"]) == 3 and set(_kategori(en)) == {"sunscreen"} and k1["profil"]["tipe_kulit"] == "berminyak"
        and set(_kategori(en2)) == {"moisturizer"} and k2["profil"]["tipe_kulit"] == "kering"
        and k2["profil"]["budget_max"] == 100000 and all(h <= 100000 for h in _harga(en2))
        and en3["tipe"] == "alasan" and indo and _bahasa_indonesia(en3["explanation"]),
        f"'give me 3 sunscreen...oily skin' -> {len(en['recommendation'])} sunscreen, tipe {k1['profil']['tipe_kulit']}; "
        f"'moisturizer for dry skin between 50k and 100k' -> budget {k2['profil']['budget_max']}; 'why is number 1 "
        f"recommended?' -> {en3['tipe']}; penjelasan: {en['explanation'][:90]!r}")

    # 7.7 banyak permintaan dalam 1 pesan
    _, m1 = chat("kasih 3 serum sama 2 toner buat kulit berminyak dibawah 50rb", ob)
    grup = {g["judul"]: len(g["produk"]) for g in (m1["grup"] or [])}
    _, m2 = chat("rekomendasiin sunscreen dong, terus bandingin nomor 1 sama 2", ob)
    _, m3 = chat("budgetnya 100rb aja terus urutin dari yang termurah", ob, m2["konteks"])
    tampil = m2["konteks"]["tampil"]
    cek("7.7", "Banyak permintaan dalam 1 pesan -> semuanya dikerjakan: 2 kategori jadi 2 kelompok dengan filter sama; "
               "rekomendasi + perbandingan / ganti budget + urutkan dikerjakan berurutan",
        grup.get("Serum", 0) >= 1 and grup.get("Toner", 0) >= 1 and grup.get("Serum", 0) <= 3 and grup.get("Toner", 0) <= 2
        and m1["konteks"]["profil"]["tipe_kulit"] == "berminyak" and all(h <= 50000 for h in _harga(m1))
        and len(m2["recommendation"]) == 3 and m2["perbandingan"] and len(m2["perbandingan"]["produk"]) == 2
        and m2["perbandingan"]["produk"][0].startswith("#1 ") and m2["perbandingan"]["produk"][1].startswith("#2 ")
        and m3["konteks"]["profil"]["budget_max"] == 100000 and _harga(m3) == sorted(_harga(m3))
        and "Budget aku ubah" in m3["explanation"] and "diurutkan" in m3["explanation"] and len(tampil) == 3,
        f"serum+toner -> kelompok {grup}, harga maks {max(_harga(m1) or [0]):,.0f}; 'rekomendasiin ... terus "
        f"bandingin 1 sama 2' -> {len(m2['recommendation'])} produk + tabel {m2['perbandingan']['produk'] if m2['perbandingan'] else None}; "
        f"'budget 100rb terus urutin termurah' -> {_harga(m3)}")

    # 7.8 Groq bermasalah -> tetap ada rekomendasi dari CBF, tidak nge-hang
    import socket
    import threading
    import time
    cbf = _mesin_lokal()
    import generate_jawaban
    from groq import Groq
    from percakapan import Percakapan
    diam = socket.socket()
    diam.bind(("127.0.0.1", 0))
    diam.listen(5)  # menerima koneksi tapi tidak pernah menjawab = Groq "hang"
    koneksi = []  # disimpan supaya koneksinya tidak ditutup (harus menggantung, bukan ditolak)

    def _terima():
        try:
            while True:
                koneksi.append(diam.accept())
        except OSError:  # socket ditutup di akhir tes
            pass
    threading.Thread(target=_terima, daemon=True).start()
    skenario = {"API key salah (401)": dict(api_key="kunci-salah"),
                "server mati (koneksi ditolak)": dict(api_key="x", base_url="http://127.0.0.1:9"),
                "server hang (timeout)": dict(api_key="x", base_url=f"http://127.0.0.1:{diam.getsockname()[1]}")}
    batas_asli = generate_jawaban.BATAS_WAKTU_LLM
    generate_jawaban.BATAS_WAKTU_LLM = 8.0  # agar tes cepat; di produksi 30 detik
    hasil_llm = {}
    try:
        for nama, opsi in skenario.items():
            gen = generate_jawaban.GeneratorJawaban(cbf)
            gen.client = Groq(timeout=25.0, max_retries=0, **opsi)
            pc = Percakapan(cbf, gen)
            t0 = time.time()
            r1 = pc.proses("rekomendasiin sunscreen dong", None, ob)
            t1 = time.time() - t0
            t0 = time.time()
            r2 = pc.proses("carikan toner", None, ob)
            t2 = time.time() - t0
            hasil_llm[nama] = (len(r1["recommendation"]), "Penjelasan AI lagi nggak tersedia" in r1["explanation"],
                               t1, t2, len(r2["recommendation"]))
    finally:
        generate_jawaban.BATAS_WAKTU_LLM = batas_asli
        diam.close()
    cek("7.8", "Groq error/mati/hang -> tetap kasih rekomendasi dari CBF + penjelasan otomatis (bilang AI lagi nggak "
               "tersedia), dibatasi waktu; pesan berikutnya langsung tanpa nunggu LLM lagi",
        all(n1 == 3 and catat and t1 < 12 and t2 < 3 and n2 >= 1 for n1, catat, t1, t2, n2 in hasil_llm.values()),
        "; ".join(f"{nama}: {n1} produk, catatan={catat}, {t1:.1f} dtk, pesan berikutnya {t2:.1f} dtk"
                  for nama, (n1, catat, t1, t2, _) in hasil_llm.items()))

    # 7.9 RAG tidak tersedia -> tetap jalan pakai CBF
    import rag_retrieve

    class RAGRusak:
        def ambil_konteks(self, *args, **kwargs):
            raise RuntimeError("ChromaDB tidak bisa dibaca")

    asli_dir = rag_retrieve.CHROMA_DIR
    rag_retrieve.CHROMA_DIR = Path("data/folder_yang_tidak_ada")
    try:
        rag_retrieve.RAGRetriever()
        gagal_muat = False
    except FileNotFoundError:
        gagal_muat = True  # backend menangkap ini di startup -> mesin["rag"] = None
    finally:
        rag_retrieve.CHROMA_DIR = asli_dir
    hasil_rag = {}
    for nama, rag in (("RAG tidak ada (None)", None), ("RAG rusak saat dipakai", RAGRusak())):
        pc = Percakapan(cbf, None, rag)
        r = pc.proses("rekomendasiin sunscreen dong", None, ob)
        u = pc.proses("ada review bagus soal nomor 1 ga?", r["konteks"], ob)
        hasil_rag[nama] = (len(r["recommendation"]), u["tipe"], "ulasan positif dari" in u["explanation"],
                           "> \"" not in u["explanation"])
    # startup backend yang ASLI dijalankan dengan RAG yang gagal dimuat -> backend
    # harus tetap siap (rag None), bukan ikut mati
    import asyncio
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    import backend.main as bm

    def _rag_gagal():
        raise FileNotFoundError("data/chroma_db belum ada")

    async def _startup():
        async with bm.lifespan(bm.app):
            return bm.mesin["rag"], "percakapan" in bm.mesin

    asli_rag = bm.RAGRetriever
    bm.RAGRetriever = _rag_gagal
    try:
        rag_saat_startup, siap = asyncio.run(_startup())
        tangkap = rag_saat_startup is None and siap
    except Exception:
        tangkap = False
    finally:
        bm.RAGRetriever = asli_rag
    cek("7.9", "ChromaDB/RAG tidak tersedia -> chat tetap jalan pakai CBF; tanya ulasan dijawab dari ringkasan data "
               "(tanpa kutipan), bukan error",
        gagal_muat and tangkap and all(n == 3 and t == "ulasan" and ringkas and tanpa_kutip
                                       for n, t, ringkas, tanpa_kutip in hasil_rag.values()),
        f"index hilang -> RAGRetriever raise FileNotFoundError={gagal_muat}, startup backend menangkapnya={tangkap}; "
        + "; ".join(f"{nama}: {n} produk, tanya ulasan -> {t}, ringkasan data={ringkas}, tanpa kutipan={tk}"
                    for nama, (n, t, ringkas, tk) in hasil_rag.items()))


# ---------------- BAGIAN 8: kelengkapan data ----------------

_POLA_KLAIM_TIPE = __import__("re").compile(
    r"(cocok|pas|ideal|aman|ramah|ditujukan|dirancang|diformulasikan)\s+(untuk|buat|bagi|di)\s+(semua jenis kulit|"
    r"segala jenis kulit|(tipe\s+)?kulit\s+(berminyak|kering|kombinasi|sensitif|normal))", __import__("re").I)
_POLA_JUJUR = __import__("re").compile(r"(belum|tidak|nggak|gak) ada (data|info)|terbatas|belum (jelas|diketahui)",
                                       __import__("re").I)


class _GeneratorPalsu:
    """Pengganti LLM yang menulis KLAIM yang sama untuk semua produk --
    menguji penjaga klaim di Percakapan: klaim tanpa dasar data wajib dibuang,
    klaim yang didukung data tetap dipakai (jadi penjaganya selektif)."""

    def __init__(self, klaim):
        self.klaim = klaim

    def narasi(self, produk_df, profil, pertanyaan=None):
        return {"explanation": "Penjelasan umum.", "alasan_per_produk": [self.klaim] * len(produk_df)}


def _uji_klaim(cbf, klaim, pesan, ob):
    """-> {id: klaim dipertahankan?} untuk produk hasil pesan."""
    from percakapan import Percakapan
    r = Percakapan(cbf, _GeneratorPalsu(klaim)).proses(pesan, None, {**ob, "tanpa_batas_budget": False})
    return {x["id"]: x["alasan"] == klaim for x in r["recommendation"]}


def uji_bagian_8():
    print("\n=== BAGIAN 8: Kelengkapan data ===")
    import re
    import pandas as pd
    katalog = pd.read_csv(ROOT / "data" / "products_final.csv").set_index("id")
    tipe_kosong = lambda pid: pd.isna(katalog.at[pid, "tipe_kulit_cocok"])  # noqa: E731
    kand_kosong = lambda pid: pd.isna(katalog.at[pid, "kandungan"])  # noqa: E731
    ob = {"tipe_kulit": "kombinasi", "masalah_kulit": ["hiperpigmentasi"], "budget": 120000}
    _, d = chat("kasih 5 moisturizer", ob)
    kosong = [x for x in d["recommendation"] if tipe_kosong(x["id"])]
    nomor = kosong[0]["nomor"] if kosong else 1
    _, alasan = chat(f"kenapa nomor {nomor} direkomendasiin?", ob, d["konteks"])

    cbf = _mesin_lokal()
    from percakapan import BAHAN_AKTIF
    lima_tipe = lambda pid: not tipe_kosong(pid) and len(str(katalog.at[pid, "tipe_kulit_cocok"]).split(";")) == 5  # noqa: E731
    klaim_tipe = _uji_klaim(cbf, "Cocok untuk semua jenis kulit.", "kasih 10 moisturizer", ob)
    tipe_benar = all(simpan == lima_tipe(pid) for pid, simpan in klaim_tipe.items())
    cek("8.1", "tipe_kulit_cocok kosong -> boleh direkomendasikan, tapi jujur 'belum ada data pasti' (kartu, alasan, "
               "penjelasan); klaim 'cocok untuk kulit X' dari LLM yang tidak didukung data dibuang",
        kosong and all(any("Belum ada data pasti soal kecocokan tipe kulit" in c for c in x["catatan"]) for x in kosong)
        and all(not _POLA_KLAIM_TIPE.search(x["alasan"]) or _POLA_JUJUR.search(x["alasan"]) for x in kosong)
        and "belum ada data kecocokan tipe kulit" in alasan["explanation"] and "bukan** karena pasti cocok" in alasan["explanation"]
        and tipe_benar and any(klaim_tipe.values()) and not all(klaim_tipe.values()),
        f"{len(kosong)} dari {len(d['recommendation'])} moisturizer tanpa data tipe kulit -> semua ada catatan & alasan "
        f"tanpa klaim tipe; contoh alasan: {kosong[0]['alasan'][:90] if kosong else '-'!r}; 'kenapa nomor {nomor}' -> "
        f"'belum ada data kecocokan...'; LLM palsu 'Cocok untuk semua jenis kulit' di 10 produk -> dipertahankan "
        f"{sum(klaim_tipe.values())} (yang datanya memang 5 tipe), dibuang {len(klaim_tipe) - sum(klaim_tipe.values())} "
        f"(data kosong/sebagian) -> sesuai data={tipe_benar}")

    _, bahan = chat("bahan aktifnya apa?", ob, d["konteks"])
    per_produk = bahan["explanation"].split("\n\n")
    kand_ok = True
    for x in d["recommendation"]:
        blok = next((b for b in per_produk if b.startswith(f"**#{x['nomor']} ")), "")
        if kand_kosong(x["id"]):
            kand_ok &= "tidak ada data kandungan" in blok
        else:
            pertama = re.split(r"[,;|]", str(katalog.at[x["id"], "kandungan"]))[0].strip().lower()
            kand_ok &= pertama in blok.lower()
    sumber = {pid: " ".join(str(katalog.at[pid, c]) for c in ("nama_produk", "kandungan", "deskripsi")
                            if pd.notna(katalog.at[pid, c])).lower() for pid in katalog.index}
    karang = [(x["id"], b) for x in d["recommendation"] if kand_kosong(x["id"]) for kel in BAHAN_AKTIF for b in kel
              if re.search(rf"\b{re.escape(b)}\b", x["alasan"].lower())
              and not any(re.search(rf"\b{re.escape(y)}\b", sumber[x["id"]]) for y in kel)]
    klaim_bahan = _uji_klaim(cbf, "Mengandung niacinamide yang membantu mencerahkan.", "kasih 10 serum",
                             {"tipe_kulit": "berminyak", "masalah_kulit": ["kusam"], "budget": 150000})
    ada_niacin = lambda pid: bool(re.search(r"\b(niacinamide|nicotinamide|vitamin b3|vit b3)\b", sumber[pid]))  # noqa: E731
    bahan_benar = all(simpan == ada_niacin(pid) for pid, simpan in klaim_bahan.items())
    cek("8.2", "kandungan kosong -> tidak ada klaim bahan aktif di luar data; ditanya 'bahan aktifnya apa?' -> jujur "
               "'tidak ada data kandungan' (yang ada datanya -> sesuai data)",
        bahan["tipe"] == "info_produk" and kand_ok and not karang and bahan_benar and any(klaim_bahan.values())
        and not all(klaim_bahan.values()),
        f"{sum(kand_kosong(x['id']) for x in d['recommendation'])}/{len(d['recommendation'])} produk tanpa data kandungan "
        f"-> dijawab 'tidak ada data kandungan', sisanya sesuai data={kand_ok}; klaim bahan karangan di alasan LLM asli="
        f"{karang or 'tidak ada'}; LLM palsu 'mengandung niacinamide' di 10 serum -> dipertahankan "
        f"{sum(klaim_bahan.values())} (niacinamide ada di nama/kandungan/deskripsi), dibuang "
        f"{len(klaim_bahan) - sum(klaim_bahan.values())} -> sesuai data={bahan_benar}")

    # 8.3 harga_outlier: data asli semuanya False, jadi disimulasikan -- produk
    # yang biasanya muncul teratas ditandai outlier (Rp1 miliar)
    from cbf_engine import CBFEngine
    data = pd.read_csv(ROOT / "data" / "products_final.csv")
    target = set()
    for tipe, mas, kat in (("kombinasi", "hiperpigmentasi", "moisturizer"), ("berminyak", "jerawat", "sunscreen"),
                           ("berminyak", "jerawat", "serum"), ("berminyak", "jerawat", "toner"),
                           ("berminyak", "jerawat", None), ("kering", "jerawat", None)):
        target |= set(cbf.recommend(tipe_kulit=tipe, masalah_kulit=[mas], kategori=kat, top_n=6, hanya_relevan=True)["id"])
    target = sorted(target)
    lewat_ambang = target[0]  # yang ini flag-nya False tapi harganya Rp500 juta -> tetap harus tertangkap
    data.loc[data["id"].isin(target), "harga"] = 1_000_000_000
    data.loc[data["id"].isin(target[1:]), "harga_outlier"] = True
    data.loc[data["id"] == lewat_ambang, "harga"] = 500_000_000
    tanpa_kolom = data.drop(columns=["harga_outlier"])
    bocor = {}
    from percakapan import Percakapan
    for nama_data, df in (("ada kolom harga_outlier", data), ("kolom harga_outlier hilang", tanpa_kolom)):
        mesin = CBFEngine(df=df)
        pc = Percakapan(mesin)
        muncul = set()
        for tanpa_batas, budget in ((True, None), (False, 2_000_000_000), (False, 150_000)):
            ob_ = {"tipe_kulit": "berminyak", "masalah_kulit": ["jerawat"], "budget": budget, "tanpa_batas_budget": tanpa_batas}
            k = None
            for pesan in ("rekomendasiin dong", "kasih 10 sunscreen", "yang lain dong", "banyakin", "urutin dari yang termahal",
                          "ada yang lebih murah?", "2 serum sama 2 toner", "kasih yang terbaik", "semua kategori"):
                r = pc.proses(pesan, k, ob_)
                k = r["konteks"]
                muncul |= {x["id"] for x in r["recommendation"]}
        muncul |= set(mesin.recommend(tipe_kulit="berminyak", masalah_kulit=["jerawat"], top_n=1000)["id"])
        info = pc.proses(f"harga {katalog.at[target[1], 'nama_produk']} berapa?", None, ob_)
        bocor[nama_data] = (sorted(muncul & set(target)), "tidak wajar" in info["explanation"]
                            and "1.000.000.000" not in info["explanation"])
    asli_nol = int(cbf.df["harga_outlier"].sum()) == 0
    cek("8.3", "harga_outlier=True -> tersaring dari SEMUA jalur rekomendasi (dengan/tanpa budget, kategori, multi, "
               "'yang lain', 'lebih murah', 'terbaik', urutkan, banyakin), juga kalau flag-nya tidak terisi; dicari "
               "langsung -> harganya tidak ditampilkan",
        asli_nol and all(not m and info_ok for m, info_ok in bocor.values()),
        f"{len(target)} produk teratas disimulasikan outlier (1 di antaranya cuma lewat ambang harga, flag False); "
        + "; ".join(f"{n}: outlier yang muncul={m or 'tidak ada'}, dicari langsung -> 'harga tidak wajar'={i}"
                    for n, (m, i) in bocor.items())
        + f"; data asli: harga_outlier True={int(cbf.df['harga_outlier'].sum())}")

    # 8.4 rating/sentimen kosong -> "belum ada ulasan", tidak pernah nan/None mentah
    ob4 = {"tipe_kulit": "berminyak", "masalah_kulit": ["hiperpigmentasi"], "budget": None, "tanpa_batas_budget": True}
    _, d4 = chat("rekomendasiin dong", ob4)
    nol = [x for x in d4["recommendation"] if not x["jml_ulasan"]]
    n = nol[0]["nomor"] if nol else 1
    lain = 2 if n == 1 else 1
    jawab = {}
    for pesan in (f"kenapa nomor {n} direkomendasiin?", f"review nomor {n} dong", f"bandingkan nomor {n} sama {lain}",
                  "urutin dari yang ulasannya paling positif"):
        _, jawab[pesan] = chat(pesan, ob4, d4["konteks"])
    tabel = jawab[f"bandingkan nomor {n} sama {lain}"]["perbandingan"]
    kolom = [i for i, p in enumerate(tabel["produk"]) if p.startswith(f"#{n} ")] if tabel else []
    sel = {b["atribut"]: b["nilai"][kolom[0]] for b in tabel["baris"]} if kolom else {}
    urut = jawab["urutin dari yang ulasannya paling positif"]["recommendation"]
    cek("8.4", "Produk tanpa ulasan (jml_ulasan 0, sentimen/rating NaN) -> 'belum ada ulasan'/'belum ada rating' di "
               "semua tampilan; di SELURUH respons tes bagian 1-8 tidak ada nan/None mentah",
        nol and nol[0]["skor_sentimen"] is None and nol[0]["jml_ulasan"] == 0
        and "Ulasan: belum ada ulasan" in jawab[f"kenapa nomor {n} direkomendasiin?"]["explanation"]
        and "Belum ada ulasan untuk produk ini" in jawab[f"review nomor {n} dong"]["explanation"]
        and sel.get("Ulasan") == "belum ada ulasan"
        and (sel.get("Rating") == "belum ada rating" if nol[0]["rating"] is None else sel.get("Rating", "").startswith("★"))
        and urut and urut[-1]["jml_ulasan"] == 0 and not _BOCOR,
        f"{len(nol)} produk tanpa ulasan di hasil (nomor {n}); alasan/ulasan/tabel -> 'belum ada ulasan' "
        f"(tabel: Ulasan={sel.get('Ulasan')!r}, Rating={sel.get('Rating')!r}); diurutkan 'ulasan paling positif' -> "
        f"ditaruh paling bawah; nan/None mentah di seluruh respons tes: "
        + (f"{len(_BOCOR)} -> {_BOCOR[:3]}" if _BOCOR else "0"))


BAGIAN = {1: uji_bagian_1, 2: uji_bagian_2, 3: uji_bagian_3, 4: uji_bagian_4, 5: uji_bagian_5, 6: uji_bagian_6,
          7: uji_bagian_7, 8: uji_bagian_8}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--bagian", type=int, choices=sorted(BAGIAN))
    args = parser.parse_args()
    try:
        requests.get(f"{BACKEND_URL}/health", timeout=5).raise_for_status()
    except Exception as e:
        sys.exit(f"Backend belum jalan di {BACKEND_URL} ({e}). Jalankan dulu: uvicorn backend.main:app --port 8000")

    for nomor, fungsi in BAGIAN.items():
        if args.bagian in (None, nomor):
            fungsi()

    lulus = sum(1 for *_, ok, _ in _hasil if ok)
    print(f"\n=== RINGKASAN: {lulus}/{len(_hasil)} skenario PASS ===")
    for kode, deskripsi, ok, _ in _hasil:
        if not ok:
            print(f"  FAIL {kode} {deskripsi}")
    sys.exit(0 if lulus == len(_hasil) else 1)


if __name__ == "__main__":
    main()
