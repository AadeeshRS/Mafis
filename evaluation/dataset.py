"""Frozen candidate inventory and non-generating official PDF acquisition.

Downloaded candidates are not annotated gold and never silently join inference.
"""
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
import json
from pathlib import Path
import httpx

CANDIDATES=(
    ("intel_2024","validation","https://www.intc.com/filings-reports/all-sec-filings/content/0000050863-25-000052/a2024arsform10-k.pdf"),
    ("microsoft_2024","validation","https://www.sec.gov/Archives/edgar/data/789019/000119312524242888/d815777dars.pdf"),
    ("walmart_2024","validation","https://corporate.walmart.com/content/dam/corporate/documents/newsroom/2024/04/25/walmart-releases-2024-annual-report-and-proxy-statement/walmart-inc-2024-annual-report.pdf"),
    ("alphabet_2024","test","https://abc.xyz/assets/e1/57/8a65483e43feaa709f6cc5cc0737/annualreport2024-web.pdf"),
    ("nike_2024","test","https://www.sec.gov/Archives/edgar/data/320187/000130817924000659/nke4278571-ars.pdf"),
    ("amazon_2024","test","https://s2.q4cdn.com/299287126/files/doc_financials/2025/ar/Amazon-2024-Annual-Report.pdf"),
    ("pepsico_2024","test","https://www.pepsico.com/docs/default-source/annual-reports/2024-pepsico-annual-report.pdf"),
    ("netflix_2024","test","https://ir.netflix.net/financials/annual-reports-and-proxies/"),
    ("meta_2024","test","https://investor.atmeta.com/financials/"),
)

# Official issuer mirrors discovered after the original acquisition failures.
# Both attempts remain in the acquisition record; split membership is unchanged.
ALTERNATIVES={
    "alphabet_2024":"https://abc.xyz/assets/99/21/46cafdba41089a12a2d86ea47d44/goog026-annualreport2024-web.pdf",
    "nike_2024":"https://investors.nike.com/_assets/_3064c626b80c9d8918cd39931fcf3802/nike/db/950/9329/annual_report/427857-1-_7_Nike-2024-Combo_Form-10-K_WR.pdf",
    "pepsico_2024":"https://www.pepsico.com/docs/pepsico-5v9wci20/media/Files/investors/2024-pepsico-annual-report-01.pdf",
    "netflix_2024":"https://s22.q4cdn.com/959853165/files/doc_financials/2024/ar/Netflix-10-K-01272025.pdf",
    "meta_2024":"https://s21.q4cdn.com/399680738/files/doc_financials/2024/ar/Meta-12-31-2024-10K-ARS.pdf",
}
RESERVE=("amd_2024","validation","https://ir.amd.com/financial-information/sec-filings/content/0001193125-25-067185/0001193125-25-067185.pdf")


def acquire(output="output/batch2/dataset",include_reserve=False):
    root=Path(output);root.mkdir(parents=True,exist_ok=True)
    existing=json.loads(Path("tests/fixtures/phase1_cases.json").read_text())["cases"]
    inventory=[{"case_id":c["case_id"],"split":"development","source_url":c["document"]["source_url"],
        "sha256":sha256(Path(c["document"]["path"]).read_bytes()).hexdigest(),"annotation":"Existing source-inspected annotations; prior development exposure"} for c in existing]
    candidates=CANDIDATES+(RESERVE,) if include_reserve else CANDIDATES
    frozen={"existing_cases":inventory,"candidate_splits":candidates,
        "remaining_test_slots":0,"target_total":12,"held_out_evaluated":False,
        "note":"Candidate downloads/discovery pages are not gold. Landing pages require a resolved official PDF link."}
    frozen["split_hash"]=sha256(json.dumps(frozen,sort_keys=True).encode()).hexdigest()
    if (root/"split_freeze.json").exists() and json.loads((root/"split_freeze.json").read_text())["split_hash"]!=frozen["split_hash"]:
        raise ValueError("Refusing to overwrite a different frozen split inventory")
    (root/"split_freeze.json").write_text(json.dumps(frozen,indent=2),encoding="utf-8")
    def fetch(item):
        name,split,url=item
        result={"case_id":name,"split":split,"source_url":url,"annotation_status":"not yet independently annotated","test_contamination":False}
        result["attempts"]=[]
        for attempted_url in dict.fromkeys((url,ALTERNATIVES.get(name,url))):
            try:
                response=httpx.get(attempted_url,timeout=20,follow_redirects=True)
                result["attempts"].append({"url":attempted_url,"http_status":response.status_code})
                if response.status_code==200 and response.content.startswith(b"%PDF"):
                    (root/(name+".pdf")).write_bytes(response.content)
                    result.update(source_url=attempted_url,sha256=sha256(response.content).hexdigest(),bytes=len(response.content),status="downloaded_candidate_not_gold")
                    break
                result["status"]="download_failed_or_not_pdf"
            except Exception as exc:
                result["attempts"].append({"url":attempted_url,"error_type":type(exc).__name__})
                result.update(status="download_failed")
        return result
    results=list(ThreadPoolExecutor(max_workers=4).map(fetch,candidates))
    (root/"acquisition.json").write_text(json.dumps(results,indent=2),encoding="utf-8")
    print(json.dumps(results,indent=2))


if __name__=="__main__":
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument("--output",default="output/batch2/dataset_reproduce")
    parser.add_argument("--include-reserve",action="store_true")
    args=parser.parse_args();acquire(args.output,include_reserve=args.include_reserve)
