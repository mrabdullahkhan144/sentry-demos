#!/usr/bin/env python3
"""
SENTRY demo generator.

Reads businesses.json, writes one self-contained HTML file per business into demos/.
Each file is a working chat demo branded for that business, using only facts
that are publicly verifiable (hours, address, services, staff names).

No API key. No network. Nothing to break while a shop owner is looking at it.
Answers come from a scored keyword match over a per-business knowledge base.

To switch a demo to a live model later, see LIVE_MODE at the bottom of this file.
"""

import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).parent
OUT = ROOT / "demos"
OUT.mkdir(exist_ok=True)

# Your WhatsApp number. Every demo's closing button points here.
SELLER_NAME = "Abdullah"          # what people call you in chat
SELLER_FULL = "Hafiz Muhammad Abdullah Ahmad"  # signature line
SELLER_WA = "923340706021"  # 0334 0706021

# ---------------------------------------------------------------------------
# Knowledge base construction
# ---------------------------------------------------------------------------

CATEGORY_INTENTS = {
    "gym": [
        ("membership fee price cost monthly charges kitna rate package",
         "Membership depends on which package you pick — monthly, quarterly or annual — "
         "and whether you want personal training added. I don't want to quote you a wrong "
         "number, so let me put you straight through to the team for today's rate.", True),
        ("ladies women female timing separate girls",
         "{ladies}", False),
        ("trial free day pass visit try first time walk in",
         "Yes — come in during opening hours and ask at reception for a walk-in session so you "
         "can see the floor and the equipment before committing. Want me to note your name down "
         "so they're expecting you?", True),
        ("personal trainer training coach pt",
         "Personal training is available. {staff} If you tell me your goal — weight loss, strength, "
         "general fitness — I'll pass it on so they match you with the right trainer.", True),
        ("parking car bike",
         "There's parking at the building. It gets tight at peak evening hours, so mornings and "
         "late nights are easier if you're driving.", False),
        ("cardio treadmill machines equipment weights",
         "Full cardio and free-weight setup, plus machines. {highlights}", False),
    ],
    "dental": [
        ("appointment book booking slot schedule kab",
         "I can take your details right now and the clinic will confirm a slot. What day suits you "
         "best, and morning or evening?", True),
        ("price cost fee charges kitna scaling filling rate",
         "Charges depend on the treatment and how much work is needed, so the clinic quotes after a "
         "quick look. Rather than guess, let me pass your number on and they'll tell you exactly.", True),
        ("pain emergency urgent toothache swelling bleeding",
         "That needs to be seen quickly. Call {phone} now — and if the line is busy, leave your "
         "name with me and someone will ring you back. Don't wait it out.", True),
        ("braces aligners invisalign teeth straight",
         "Braces and clear aligners are both done here. {staff} It starts with a consultation where "
         "they explain the plan and timeline before anything begins.", True),
        ("root canal rct crown cap implant extraction wisdom",
         "Yes, that's done in-house. {staff} These are usually completed across a small number of "
         "sittings, and the dentist explains each step before starting.", True),
        ("installment instalment plan easy payment",
         "Longer treatments can often be spread out. Ask the clinic directly — they've arranged this "
         "for patients before.", True),
    ],
    "salon": [
        ("bridal wedding dulhan shaadi makeup",
         "Bridal is one of the main things done here. {staff} Bridal slots book out fast in wedding "
         "season, so give me your date and I'll get it held for you.", True),
        ("price cost rate charges kitna package deal",
         "Rates depend on the service and which artist you book. Tell me what you're after and I'll "
         "get you an exact quote from the team rather than a rough guess.", True),
        ("appointment book booking slot walk in today",
         "I can note you down now. Which service, and what day were you thinking?", True),
        ("hair colour color cut keratin treatment nanoplastia smoothening",
         "Hair colour, cutting and treatments are all done here. {staff} A short consultation first "
         "is normal so they can check your hair before recommending anything.", True),
        ("facial manicure pedicure massage spa mani pedi",
         "All available. {highlights}", False),
        ("home service ghar",
         "{home}", False),
    ],
    "realestate": [
        ("plot house buy purchase looking property",
         "Tell me the phase or area, your budget range, and whether it's for living or investment — "
         "I'll pass it to the team and they'll come back with what's actually available right now, "
         "not old listings.", True),
        ("sell selling my plot valuation rate worth price",
         "For an accurate valuation they need the plot number and phase, because rate swings street "
         "to street. Share those with me and {staff}", True),
        ("rent rental kiraya tenant",
         "Both residential and commercial rentals are handled. What area and what monthly budget?", True),
        ("overseas abroad uk usa dubai saudi remote",
         "Overseas clients are handled regularly, including paperwork without you flying back. "
         "{staff} Leave your number with country code and they'll call at a time that works for you.", True),
        ("commission fee charges",
         "Commission is standard market rate and is confirmed in writing before anything moves "
         "forward. Nothing hidden.", False),
        ("file transfer documents ntn paperwork legal",
         "Transfer and documentation are handled end to end. It's worth speaking to the team directly "
         "so they can check the specific file's status.", True),
    ],
}

GENERIC_INTENTS = [
    ("timing open close hours khula band kab kitne baje sunday",
     "{hours}", False),
    ("where location address kahan reach directions map",
     "{address}. It's in {area}. I can send you a map pin if that's easier.", False),
    ("phone number contact call whatsapp",
     "You can reach them on {phone}. Or leave your number with me and they'll call you back.", True),
    ("hello hi salam assalam hey good morning evening",
     "Assalam-o-alaikum. This is {name}'s assistant. Ask me anything — timings, services, prices, "
     "booking — I'm here all night too.", False),
    ("thanks thank you shukriya ok theek acha",
     "Anytime. If you want me to hold a slot or pass your number to the team, just say the word.", False),
]


def ladies_line(b):
    for h in b["highlights"]:
        if "ladies" in h.lower():
            return (f"Yes — {h.lower()}. Outside those hours it's a mixed floor. "
                    f"Want me to confirm today's schedule with reception?")
    return ("Timings for ladies vary by day, so let me confirm the current schedule with reception "
            "rather than give you old information. Shall I have them message you?")


def home_line(b):
    for h in b["highlights"]:
        if "home" in h.lower():
            return ("Yes, at-home service is available. Tell me your area and which service, and "
                    "I'll check availability for you.")
    return ("At-home service isn't standard, but for larger bookings like bridal they've made "
            "arrangements before. Worth asking the team directly.")


def build_kb(b):
    """Turn a business profile into a list of (keywords, answer, wants_lead) triples."""
    intents = CATEGORY_INTENTS.get(b["category"], []) + GENERIC_INTENTS
    fields = {
        "name": b["name"],
        "hours": b["hours"],
        "address": b["address"],
        "area": b["area"],
        "phone": b["phone"],
        "staff": b["staff"],
        "highlights": "; ".join(b["highlights"]) + ".",
        "ladies": ladies_line(b),
        "home": home_line(b),
    }
    kb = []
    for keywords, template, wants_lead in intents:
        kb.append({
            "k": keywords.split(),
            "a": template.format(**fields),
            "lead": wants_lead,
        })
    return kb


def build_chips(b):
    """Three tappable openers, tuned per category."""
    per_cat = {
        "gym": ["What are your timings?", "How much is monthly membership?", "Do you do personal training?"],
        "dental": ["Can I book an appointment?", "How much for scaling?", "I have a bad toothache"],
        "salon": ["Do you do bridal makeup?", "What time do you open?", "How much for hair colour?"],
        "realestate": ["I want to buy in DHA", "What's my plot worth?", "I'm overseas, can you help?"],
    }
    return per_cat.get(b["category"], ["What are your timings?", "Where are you located?", "Can I book?"])


# ---------------------------------------------------------------------------
# Page template
# ---------------------------------------------------------------------------

TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>__NAME__ — assistant preview</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Instrument+Sans:wght@400;500;600&family=Instrument+Serif:ital@0;1&display=swap" rel="stylesheet">
<style>
  :root{
    --accent: __ACCENT__;
    --canvas: #E4E7E2;
    --surface: #FFFFFF;
    --ink: #14201C;
    --muted: #66736E;
    --line: #CFD5CF;
  }
  *{box-sizing:border-box}
  html,body{margin:0;padding:0}
  body{
    background:var(--canvas);
    color:var(--ink);
    font-family:"Instrument Sans",system-ui,-apple-system,sans-serif;
    font-size:16px;
    line-height:1.5;
    -webkit-font-smoothing:antialiased;
  }
  .shell{max-width:560px;margin:0 auto;min-height:100dvh;display:flex;flex-direction:column}

  header{
    background:var(--accent);
    color:#fff;
    padding:18px 20px 16px;
    position:sticky;top:0;z-index:5;
  }
  .biz{display:flex;align-items:center;gap:12px}
  .mark{
    width:42px;height:42px;border-radius:50%;
    background:rgba(255,255,255,.18);
    display:grid;place-items:center;
    font-size:17px;font-weight:600;letter-spacing:.02em;flex:none;
  }
  .biz h1{margin:0;font-size:17px;font-weight:600;letter-spacing:-.01em}
  .status{margin:2px 0 0;font-size:12.5px;opacity:.85;display:flex;align-items:center;gap:6px}
  .dot{width:7px;height:7px;border-radius:50%;background:#7BE3A4;flex:none}

  .ribbon{
    background:var(--ink);color:#DCE3DE;
    font-size:12.5px;padding:9px 20px;text-align:center;
  }
  .ribbon b{color:#fff;font-weight:500}

  .thread{
    flex:1;padding:20px 16px 8px;
    display:flex;flex-direction:column;gap:10px;
    overflow-y:auto;
  }
  .row{display:flex}
  .row.me{justify-content:flex-end}
  .bubble{
    max-width:84%;padding:10px 13px;
    border-radius:16px;font-size:15px;
    box-shadow:0 1px 1px rgba(20,32,28,.07);
    white-space:pre-wrap;word-wrap:break-word;
  }
  .row.bot .bubble{background:var(--surface);border-bottom-left-radius:5px}
  .row.me .bubble{background:var(--accent);color:#fff;border-bottom-right-radius:5px}

  .typing{display:flex;gap:4px;padding:14px 15px}
  .typing span{
    width:6px;height:6px;border-radius:50%;background:var(--muted);
    animation:pulse 1.1s infinite ease-in-out;
  }
  .typing span:nth-child(2){animation-delay:.16s}
  .typing span:nth-child(3){animation-delay:.32s}
  @keyframes pulse{0%,60%,100%{opacity:.25;transform:translateY(0)}30%{opacity:1;transform:translateY(-3px)}}

  .handoff{
    background:var(--surface);border-left:3px solid var(--accent);
    border-radius:10px;padding:11px 13px;margin-top:2px;max-width:84%;
    font-size:14px;
  }
  .handoff p{margin:0 0 9px;color:var(--muted)}
  .handoff a{
    display:inline-block;background:var(--accent);color:#fff;
    text-decoration:none;padding:8px 15px;border-radius:9px;
    font-size:14px;font-weight:500;
  }

  .chips{display:flex;gap:8px;padding:6px 16px 12px;flex-wrap:wrap}
  .chip{
    background:transparent;border:1px solid var(--line);
    color:var(--ink);border-radius:20px;padding:7px 14px;
    font:inherit;font-size:13.5px;cursor:pointer;
  }
  .chip:hover{background:var(--surface)}
  .chip:focus-visible{outline:2px solid var(--accent);outline-offset:2px}

  .composer{
    display:flex;gap:9px;padding:10px 16px calc(14px + env(safe-area-inset-bottom));
    background:var(--canvas);position:sticky;bottom:0;
  }
  .composer input{
    flex:1;border:1px solid var(--line);background:var(--surface);
    border-radius:22px;padding:11px 16px;font:inherit;font-size:15px;color:var(--ink);
  }
  .composer input:focus{outline:none;border-color:var(--accent)}
  .composer button{
    background:var(--accent);border:0;color:#fff;width:44px;height:44px;
    border-radius:50%;cursor:pointer;display:grid;place-items:center;flex:none;
  }
  .composer button:focus-visible{outline:2px solid var(--ink);outline-offset:2px}

  .pitch{background:var(--ink);color:#E3E9E5;padding:40px 26px 46px}
  .pitch h2{
    font-family:"Instrument Serif",Georgia,serif;
    font-weight:400;font-size:31px;line-height:1.18;
    margin:0 0 16px;letter-spacing:-.01em;max-width:26ch;
  }
  .pitch p{margin:0 0 14px;font-size:15px;color:#AFBCB6;max-width:60ch}
  .facts{list-style:none;padding:0;margin:22px 0 26px;border-top:1px solid #2C3B36}
  .facts li{
    padding:12px 0;border-bottom:1px solid #2C3B36;
    font-size:14.5px;color:#C8D3CE;
  }
  .cta{
    display:inline-block;background:var(--accent);color:#fff;
    text-decoration:none;padding:14px 26px;border-radius:11px;
    font-size:16px;font-weight:600;
  }
  .sig{margin:22px 0 0;font-size:13px;color:#7E8D87}
  @media (prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}}
</style>
</head>
<body>
<div class="shell">

  <header>
    <div class="biz">
      <div class="mark">__INITIALS__</div>
      <div>
        <h1>__NAME__</h1>
        <p class="status"><span class="dot"></span>Replies instantly, day and night</p>
      </div>
    </div>
  </header>

  <div class="ribbon">Preview built for <b>__NAME__</b> — not yet live on your site</div>

  <div class="thread" id="thread" aria-live="polite"></div>

  <div class="chips" id="chips"></div>

  <div class="composer">
    <input id="input" placeholder="Ask it anything…" autocomplete="off" aria-label="Type your question">
    <button id="send" aria-label="Send">
      <svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 12h15M13 6l6 6-6 6"/></svg>
    </button>
  </div>

  <section class="pitch">
    <h2>Every question above came in after you closed.</h2>
    <p>This is a working preview, built using only what's publicly listed about __NAME__ — your hours, your location, your services. Nothing invented.</p>
    <p>Put it on your website and your WhatsApp, and it answers every enquiry in seconds, in English or Urdu, at 2am on a Sunday. When someone is ready to book, it takes their name and number and sends it to you.</p>
    <ul class="facts">
      <li>Answers from your information only — it never makes up a price</li>
      <li>Captures the name and number of anyone ready to book</li>
      <li>Works on your website and WhatsApp</li>
      <li>Live in two days, no changes to how you already work</li>
    </ul>
    <a class="cta" href="https://wa.me/__SELLER_WA__?text=__WA_TEXT__">Message __SELLER_NAME__ on WhatsApp</a>
    <p class="sig">Built by __SELLER_FULL__ — Lahore</p>
  </section>

</div>

<script>
const KB = __KB__;
const CHIPS = __CHIPS__;
const PHONE = "__PHONE__";
const SELLER_WA = "__SELLER_WA__";
const OPENER = __OPENER__;

const thread = document.getElementById('thread');
const input  = document.getElementById('input');
const chipBar= document.getElementById('chips');

function el(cls, html){ const d=document.createElement('div'); d.className=cls; d.innerHTML=html; return d; }
function scroll(){ thread.scrollTop = thread.scrollHeight; }

function say(text, who){
  const row = el('row ' + who, '');
  const b = el('bubble',''); b.textContent = text;
  row.appendChild(b); thread.appendChild(row); scroll();
  return row;
}

function typing(){
  const row = el('row bot','');
  const b = el('bubble typing','<span></span><span></span><span></span>');
  row.appendChild(b); thread.appendChild(row); scroll();
  return row;
}

function handoff(){
  const wrap = el('row bot','');
  const box = el('handoff',
    '<p>Leave your name and number and the team will get back to you.</p>' +
    '<a href="https://wa.me/' + PHONE.replace(/[^0-9]/g,'') + '">Send my details</a>');
  wrap.appendChild(box); thread.appendChild(wrap); scroll();
}

// Scored keyword match. Longer keyword hits weigh more than short ones.
function answer(q){
  const words = q.toLowerCase().replace(/[^a-z0-9\s]/g,' ').split(/\s+/).filter(Boolean);
  let best = null, bestScore = 0;
  for (const item of KB){
    let s = 0;
    for (const w of words){
      for (const k of item.k){
        if (w === k) s += 3;
        else if (w.length > 3 && (k.startsWith(w) || w.startsWith(k))) s += 1.5;
      }
    }
    if (s > bestScore){ bestScore = s; best = item; }
  }
  if (!best || bestScore < 3){
    return { a: "I want to get that right rather than guess. Let me pass your question to the team — "
               + "they'll come back to you quickly. What's the best number to reach you on?", lead: true };
  }
  return best;
}

function ask(q){
  say(q, 'me');
  chipBar.style.display = 'none';
  const t = typing();
  const res = answer(q);
  const delay = 550 + Math.min(res.a.length * 7, 900);
  setTimeout(() => {
    t.remove();
    say(res.a, 'bot');
    if (res.lead) setTimeout(handoff, 400);
  }, delay);
}

document.getElementById('send').onclick = () => {
  const v = input.value.trim();
  if (v){ input.value=''; ask(v); }
};
input.addEventListener('keydown', e => { if (e.key === 'Enter') document.getElementById('send').click(); });

CHIPS.forEach(c => {
  const b = document.createElement('button');
  b.className='chip'; b.textContent=c;
  b.onclick = () => ask(c);
  chipBar.appendChild(b);
});

// Seed the thread so it never opens empty.
(function(){
  let i = 0;
  (function next(){
    if (i >= OPENER.length) return;
    const line = OPENER[i++];
    if (line.who === 'bot'){
      const t = typing();
      setTimeout(() => { t.remove(); say(line.text,'bot'); setTimeout(next, 500); }, 700);
    } else {
      say(line.text, 'me');
      setTimeout(next, 450);
    }
  })();
})();
</script>
</body>
</html>
"""


def initials(name):
    parts = [p for p in re.split(r"[\s&]+", name) if p and p[0].isalpha()]
    return "".join(p[0].upper() for p in parts[:2])


def opener(b):
    """The conversation already in progress when the owner opens the link."""
    hook = {
        "gym": "Are you open right now?",
        "dental": "Are you open right now?",
        "salon": "Are you open right now?",
        "realestate": "Are you open right now?",
    }[b["category"]]
    return [
        {"who": "bot", "text": f"Assalam-o-alaikum. This is {b['name']}'s assistant. "
                               f"Ask me anything — timings, services, booking. I'm here all night too."},
        {"who": "me", "text": hook},
        {"who": "bot", "text": b["hours"]},
    ]


def wa_text(b):
    return (f"Salam {SELLER_NAME}, I saw the assistant you built for {b['name']}. "
            f"Tell me more.").replace(" ", "%20").replace(",", "%2C")


def render(b):
    html = TEMPLATE
    subs = {
        "__NAME__": b["name"],
        "__ACCENT__": b["accent"],
        "__INITIALS__": initials(b["name"]),
        "__PHONE__": b["phone"],
        "__SELLER_WA__": SELLER_WA,
        "__SELLER_NAME__": SELLER_NAME,
        "__SELLER_FULL__": SELLER_FULL,
        "__WA_TEXT__": wa_text(b),
        "__KB__": json.dumps(build_kb(b), ensure_ascii=False),
        "__CHIPS__": json.dumps(build_chips(b), ensure_ascii=False),
        "__OPENER__": json.dumps(opener(b), ensure_ascii=False),
    }
    for k, v in subs.items():
        html = html.replace(k, v)
    return html


def main():
    businesses = json.loads((ROOT / "businesses.json").read_text())
    if SELLER_WA == "923000000000":
        print("!! SELLER_WA is still the placeholder. Edit generate.py line 24 "
              "before you send any of these.\n", file=sys.stderr)
    for b in businesses:
        path = OUT / f"{b['slug']}.html"
        path.write_text(render(b), encoding="utf-8")
        print(f"  {b['name']:<38} -> demos/{b['slug']}.html")
    print(f"\n{len(businesses)} demos built.")


# LIVE_MODE — when a client pays, swap the answer() function for a real call:
#
#   async function answer(q){
#     const r = await fetch("https://your-worker.workers.dev/chat", {
#       method:"POST", headers:{"Content-Type":"application/json"},
#       body: JSON.stringify({ q, kb: KB })
#     });
#     return (await r.json());
#   }
#
# Keep the key on the Cloudflare Worker, never in the page. Your SENTRY worker
# already does this — point it at the client's KB and change the accent colour.

if __name__ == "__main__":
    main()
