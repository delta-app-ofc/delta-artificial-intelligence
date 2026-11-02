"""Agende como processo separado, por exemplo às 20h no fuso do projeto. Default: somente simulação."""
import argparse,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

def main():
    parser=argparse.ArgumentParser(description="Alertas determinísticos do Gluh, sem chamadas a LLM")
    parser.add_argument("--execute",action="store_true",help="Grava pela API Mongo; omitir para simular")
    parser.add_argument("--user-id",type=int,action="append")
    parser.add_argument("--workers",type=int,default=4)
    args=parser.parse_args()
    from app.alerts.job import run
    report=run(args.user_id,args.execute,args.workers)
    print(json.dumps(report,ensure_ascii=False));return int(report["failed"]>0)
if __name__=="__main__": raise SystemExit(main())
