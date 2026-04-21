import gspread

gc = gspread.service_account()

sh = gc.open("MKWorld KO Lounge Updating")

print(sh.sheet1.get('A1'))