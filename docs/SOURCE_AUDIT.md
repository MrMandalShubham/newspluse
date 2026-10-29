# NewsPulse — Source Health Audit

_Audit date: 2026-10-29. 108 configured sources (RSS + HTML crawl + Google News site-search)._
_Live = HTTP reachable now and returns parseable content/links. Recent/day = articles in last 30 days ÷ 30._
_Relevance = share of that source's articles the classifier marked beauty-related (what we actually want)._

## Verdict summary

| Verdict | Count | Meaning |
|---|---|---|
| KEEP | 14 | Live, producing, on-target — keep as is |
| REVIEW | 18 | Producing but mostly off-target content (<40% beauty) — narrow or drop |
| FIX | 3 | Has history but live check now fails (block / SSL / feed) — fixable |
| CHECK | 2 | Live works but never produced — config/section issue |
| REDUNDANT | 39 | Google News site-search; publisher already captured by broad query → 0 net new |
| DROP | 32 | Dead link and no history — remove |

## RSS feeds (19)

| Live | Rgn | Source | Total | Recent/day | Last seen | Relevance | Verdict |
|---|---|---|---|---|---|---|---|
| UP | JP | prtimes.jp/main/html/searchbiscate/busi_c | 578 | 19.3 | 2026-10-28 | 6% | **REVIEW** |
| UP | JP | wwdjapan.com/category/beauty | 517 | 17.2 | 2026-10-28 | 28% | **REVIEW** |
| UP | KR | hankyung.com/distribution/beauty-fashion | 221 | 7.4 | 2026-10-28 | 1% | **REVIEW** |
| UP | KR | cosmeticsbusiness.com | 146 | 4.8 | 2026-10-28 | 90% | **KEEP** |
| UP | JP | fashionsnap.com/beauty | 133 | 4.4 | 2026-10-28 | 35% | **REVIEW** |
| UP | KR | jangup.com | 93 | 3.1 | 2026-10-28 | 90% | **KEEP** |
| UP | JP | vogue.co.jp/beauty | 72 | 2.4 | 2026-10-27 | 24% | **REVIEW** |
| UP | JP | andpremium.jp/tags/beauty | 52 | 1.7 | 2026-10-28 | 10% | **REVIEW** |
| UP | US | wwd.com/business-news | 51 | 1.7 | 2026-10-27 | 37% | **REVIEW** |
| UP | JP | kokusaishogyo-online.jp | 50 | 1.7 | 2026-10-24 | 78% | **KEEP** |
| UP | JP | glowonline.jp | 40 | 1.3 | 2026-10-28 | 52% | **KEEP** |
| DOWN | HK | wwd.com/wwd-hong-kong | 30 | 1.0 | 2026-10-24 | 7% | **FIX** |
| UP | JP | globalcosmeticsnews.com | 21 | 0.7 | 2026-10-28 | 86% | **KEEP** |
| DOWN | TH | dailyvanity.sg | 20 | 0.7 | 2026-10-28 | 100% | **FIX** |
| UP | US | wwd.com/beauty-industry-news | 20 | 0.7 | 2026-10-27 | 15% | **REVIEW** |
| UP | JP | kokusaishogyo.co.jp | 14 | 0.5 | 2026-10-24 | 7% | **REVIEW** |
| DOWN | KR | beautynury.com | 0 | 0.0 | — | — | **DROP** |
| UP | KR | koreaproductpost.com | 0 | 0.0 | — | — | **CHECK** |
| DOWN | KR | koreabizwire.com | 0 | 0.0 | — | — | **DROP** |

## HTML crawl (24)

| Live | Rgn | Source | Total | Recent/day | Last seen | Relevance | Verdict |
|---|---|---|---|---|---|---|---|
| UP | KR | slist.kr/news/articleList.html?sc_sub_s | 238 | 7.9 | 2026-10-28 | 6% | **REVIEW** |
| UP | KR | koreajoongangdaily.joins.com | 154 | 5.1 | 2026-10-28 | 1% | **REVIEW** |
| UP | KR | meconomynews.com/news/articleList.html?sc_secti | 106 | 3.5 | 2026-10-28 | 10% | **REVIEW** |
| UP | JP | biteki.com | 58 | 1.9 | 2026-10-28 | 93% | **KEEP** |
| DOWN | CN | brandstar.com.cn | 50 | 1.7 | 2026-10-28 | 20% | **FIX** |
| UP | CN | pinguan.com | 40 | 1.3 | 2026-10-27 | 95% | **KEEP** |
| UP | JP | i-voce.jp | 25 | 0.8 | 2026-10-25 | 88% | **KEEP** |
| UP | TH | vogue.co.th/beauty | 24 | 0.8 | 2026-10-27 | 79% | **KEEP** |
| UP | JP | kao.com/global/en | 20 | 0.7 | 2026-10-24 | 10% | **REVIEW** |
| UP | JP | maquia.hpplus.jp | 20 | 0.7 | 2026-10-24 | 80% | **KEEP** |
| UP | JP | kao.com/jp/newsroom/news/release | 20 | 0.7 | 2026-10-24 | 5% | **REVIEW** |
| UP | JP | syogyo.jp/news | 20 | 0.7 | 2026-10-24 | 25% | **REVIEW** |
| UP | KR | bkn24.com | 20 | 0.7 | 2026-10-24 | 75% | **KEEP** |
| UP | CN | mktindex.com | 16 | 0.5 | 2026-10-24 | 0% | **REVIEW** |
| UP | JP | kanebo-global.com | 11 | 0.4 | 2026-10-24 | 64% | **KEEP** |
| UP | JP | otonamuse.jp/beauty | 10 | 0.3 | 2026-10-24 | 10% | **REVIEW** |
| UP | CN | c2cc.cn | 6 | 0.2 | 2026-10-24 | 17% | **REVIEW** |
| DOWN | CN | nmpa.gov.cn | 0 | 0.0 | — | — | **DROP** |
| DOWN | CN | netvoices.cn | 0 | 0.0 | — | — | **DROP** |
| DOWN | JP | voce.jp | 0 | 0.0 | — | — | **DROP** |
| UP | JP | pola.co.jp/about/news | 0 | 0.0 | — | — | **CHECK** |
| DOWN | JP | kao.co.jp/biore | 0 | 0.0 | — | — | **DROP** |
| DOWN | JP | pmda.go.jp | 0 | 0.0 | — | — | **DROP** |
| DOWN | KR | cmn.co.kr/main | 0 | 0.0 | — | — | **DROP** |

## Google News site-search (65)

Only **2 of 65 ever ingested an article**, yet **41 return live Google News results** — because those publishers
(Korea Herald, Bangkok Post, Vogue India, etc.) are **already ingested by the Step-1 broad-query path**, so the
dedicated site-search finds the same articles and they dedup to zero. This whole method is mostly redundant.

**Produced (keep) (2):** beautymatter.com, chinacosmetics.com

**Redundant — live results but 0 ingested (39):** allurekorea.com, asahi.com/ajw, asia.nikkei.com/business, bangkokpost.com/beauty, caixinglobal.com, chosun.com/english, cosinkorea.com, cosme.net, cosmeticseurope.eu, daxueconsulting.com, en.people.cn, en.yna.co.kr/beauty, fashion-press.net, globaltimes.cn, harpersbazaar.in/beauty, indiaretailing.com/categories/beauty-wellness, japantimes.co.jp/beauty, japantoday.com/beauty, jeban.com, jingdaily.com, kedglobal.com/beauty, koreaherald.com/beauty, koreatimes.co.kr/beauty, mainichi.jp/english, mega-asia.com/beauty, mfds.go.kr, mk.co.kr/en, nationthailand.com/beauty, nippon.com/beauty, personalcareinsights.com, prestigeonline.com/th/beauty, pulse.mk.co.kr/beauty, retailasia.com, tatlerasia.com/th/beauty, thairath.co.th/beauty, theestablished.com/self, thenodmag.com/beauty-and-wellbeing, vogue.in, vogue.in/beauty

**Dead — no results, no history (drop) (24):** 36kr.com/user/5728075, be-story.jp, beautrium.com, beauty-matome.net, bebd.bevol.com, cbndata.com, cbo.cn/home, corp.shiseido.com/jp/news, cosmeticsdesign-asia.com, hpcnews.net, industrysourcing.cn/i/personal_care, iqingyan.cn, jumeili.cn, kevbeauty.cn, lofficielthailand.com/beauty, m.thesingle.co.kr, mylifenews.net/cosme-beauty, news.cosmmate.com, news.mynavi.jp/top/kurashi/life/health, pangjing.cn, prachachat.net/beauty, praew.com, shogyo.net, xtrend.nikkei.com/?i_cid=nbpnxr_header
