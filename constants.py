#ID of your updating spreadsheet, can be found by copying
#the part after /d/ in the sheet link
SH_KEY = '1YL5a6FdK-rC6yfdQRWeG2M39364ayvqxP7uJGmnchos'

LOOKUP_KEY = '1OCotEgMD3JC-agbl3inTql66qXzGVb9knlMypgNXc7U'

# first item is where the names go,
# second is where the placements go,
# third is where the multipliers go
updateCols = ["C", "B", "A"]

# the first item is the starting column,
# the second is the ending column
# (the total number of columns gotten
#  should be 7, including these two)
getCols = ["D", "J"]

#A1 notation of the column that Peak MMRs are stored in Player History
peakColumn = "C"

#rowOffset is = (row number of first player on Player History - 1)
#colOffset is = first Match History column on Player History
#               (column H for 150cc lounge, which is the 8th column)
rowOffset = 1
colOffset = 8

#the top row on the bot sheet to fill in for each format
sheet_start_rows = {1: 4,
                    2: 32,
                    3: 53,
                    4: 72,
                    6: 90}
#the top row on the MMR tables xlsx file to fill in for each format
table_start_rows = {1: 6,
                    2: 34,
                    3: 55,
                    4: 74,
                    6: 92}

#first value is where the name goes, second is where the penalty amount goes
pen_cells = ["C80", "D80"]
pen_cols = [3, 4]
pen_row = 80
#first cell is the start of the range, second is end of the range
get_strike_info = ["E80", "M80"]

bot_channels = [1488634624019271700]

#id of the results channels for each tier
channels = {"X": 1494770846701719582,
            "S": 1494770892050534440,
            "A": 1494770925412024573,
            "AB": 1494770959624704130,
            "B": 1494771093775581366,
            "C": 1494771093775581366,
            "D": 1494771160749965446,
            "E": 1494771201401163857,
            "F": 1494771307328569577,
            "SQ": 1488615812481810542}

#contains the emoji ID and role ID for each rank in the server;
#rank names should match up with getRank function below
ranks = { # TODO: update role IDs and emojis
    "Grandmaster": {
        "emoji": "<:grandmaster:731579876846338161>",
        "roleid": 730976842898735195},
    "Master": {
        "emoji": "<:master:731597294914502737>",
        "roleid": 445707276385386497},
    "Diamond": {
        "emoji": "<:diamond:731579813386780722>",
        "roleid": 445404401989844994},
    "Sapphire": {
        "emoji": "<:sapphire:731579851802411068>",
        "roleid": 730976660681130075},
    "Platinum": {
        "emoji": "<:platinum:542204444302114826>",
        "roleid": 445544728700649472},
    "Gold": {
        "emoji": "<:gold:731579798111125594>",
        "roleid": 445404441110380545},
    "Silver": {
        "emoji": "<:silver:731579781828575243>",
        "roleid": 445544735638159370},
    "Bronze": {
        "emoji": "<:bronze:731579759712010320>",
        "roleid": 445404463092596736},
    "Iron 2": {
        "emoji": "<:iron:731579735544430703> 2",
        "roleid": 730976738007580672},
    "Iron 1": {
        "emoji": "<:iron:731579735544430703> 1",
        "roleid": 805288798879481886}
    }

place_MMRs = {"gold": 7500,
              "silver": 6000,
              "bronze": 4500,
              "iron": 3000}

#this is where you define the MMR thresholds for each rank
def getRank(mmr: int): # TODO: update MMR thresholds
    if mmr >= 14500:
        return("Grandmaster")
    elif mmr >= 13000:
        return("Master")
    elif mmr >= 11500:
        return("Diamond")
    elif mmr >= 10000:
        return("Sapphire")
    elif mmr >= 8500:
        return("Platinum")
    elif mmr >= 7000:
        return("Gold")
    elif mmr >= 5500:
        return("Silver")
    elif mmr >= 4000:
        return("Bronze")
    elif mmr >= 2000:
        return("Iron 2")
    else:
        return ("Iron 1")

#number of players participating in events
num_players = 24

#ignore if end user
#taken from gspread.utils:
#https://github.com/burnash/gspread/blob/master/gspread/utils.py
def rowcol_to_a1(row, col):
    row = int(row)
    col = int(col)

    div = col
    column_label = ''

    while div:
        (div, mod) = divmod(div, 26)
        if mod == 0:
            mod = 26
            div -= 1
        column_label = chr(mod + 64) + column_label

    label = '%s%s' % (column_label, row)

    return label

