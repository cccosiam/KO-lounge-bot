#ID of your updating spreadsheet, can be found by copying
#the part after /d/ in the sheet link
SH_KEY = ''

LOOKUP_KEY = ''

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

#first value is where the name goes, second is where the penalty amount goes
pen_cols = [3, 4]
pen_row = 92
pen_channel = 1234567891234567890
#first cell is the start of the range, second is end of the range
get_strike_info = ["E92", "M92"]

#cell that outputs raw stats string
stats_cell = "I20"

#yeah well
profanity_whitelist = []
profanity_blacklist = []

#names of the knockout rallies. can be updated if they add more
rallies = {
    "Golden": "<:goldenrally:1496556871184213760>",
    "Ice": "<:icerally:1496556950572236830>",
    "Moon": "<:moonrally:1496557028997464144>",
    "Spiny": "<:spinyrally:1496557971633602591>",
    "Cherry": "<:cherryrally:1496558024498610386>",
    "Acorn": "<:acornrally:1496558171299516540>",
    "Cloud": "<:cloudrally:1496558293878046951>",
    "Heart": "<:heartrally:1496558347577720893>",
    "Drill": "<:drillrally:1523251786259890176>",
    "Boomerang": "<:boomerangrally:1523251808053624873>"
}

#relevant channels
key_channels = {
    "verify": 1234567891234567890,
    "penalty_log": 1234567891234567890,
    "mmr_reduction_log": 1234567891234567890,
    "verification_log": 1234567891234567890,
    "updating_log": 1234567891234567890,
    "staff_pings": 1234567891234567890,
    "name_change_request": 1234567891234567890,
    "name_change_log": 1234567891234567890,
    "pending_verification": 1234567891234567890,
    "tier-all": 1234567891234567890
}

#general channels
general_channels = {
    "general": 1234567891234567890,
    "media": 1234567891234567890,
    "bots": 1234567891234567890,
    "war_chat": 1234567891234567890,
    "strat_discussion": 1234567891234567890
}

#key roles
key_roles = {
    "player": 1234567891234567890,
    "lounge_staff": 1234567891234567890,
    "chat_restricted": 1234567891234567890,
    "muted": 1234567891234567890
}

#preseason only uses one tier so every other tier is commented out
#when it's time for tiers, use other dictionary
channels = {"ALL": 1234567891234567890}
#id of the results channels for each tier
# channels = {"X": 1234567891234567890,
#             "S": 1234567891234567890,
#             "A": 1234567891234567890,
#             "B": 1234567891234567890,
#             "C": 1234567891234567890,
#             "D": 1234567891234567890,
#             "E": 1234567891234567890,
#             "F": 1234567891234567890,
#             "SQ": 1234567891234567890}

#contains the emoji ID and role ID for each rank in the server;
#rank names should match up with getRank function below
ranks = {"Ranked": {
    "emoji": "<:dashfood:1495474890772447352>",
    "roleid": 1234567891234567890}}
# ranks = {
#     "Grandmaster": {
#         "emoji": "<:rank01grandmaster:1496556873695101019>",
#         "roleid": 1488276942959411340},
#     "Master": {
#         "emoji": "<:rank02master:1496556950572236830>",
#         "roleid": 1488277000505524224},
#     "Diamond": {
#         "emoji": "<:rank03diamond:1496557028997464144>",
#         "roleid": 1488277060198600734},
#     "Pearl": {
#         "emoji": "<:rank04pearl:1496557971633602591>",
#         "roleid": 1496535296668602418},
#     "Emerald": {
#         "emoji": "<:rank05emerald:1496558024498610386>",
#         "roleid": 1496535931757395968},
#     "Ruby": {
#         "emoji": "<:rank06ruby:1496558171299516540>",
#         "roleid": 1488277085121155193},
#     "Sapphire": {
#         "emoji": "<:rank07sapphire:1496558293878046951>",
#         "roleid": 1496536559535783987},
#     "Platinum": {
#         "emoji": "<:rank08platinum:1496558347577720893>",
#         "roleid": 1488277354156527719},
#     "Gold": {
#         "emoji": "<:rank09gold:1496558410710257797>",
#         "roleid": 1488277375127912478},
#     "Silver": {
#         "emoji": "<:rank10silver:1496558469120266330>",
#         "roleid": 1488277390453903371},
#     "Bronze": {
#         "emoji": "<:rank11bronze:1496558512552284342>",
#         "roleid": 1488277406610489505},
#     "Iron": {
#         "emoji": "<:rank12iron:1496558555724124371>",
#         "roleid": 1488277425048518736}
#     }

base_MMR = 2500
place_MMRs = {"ranked": 2500}
# place_MMRs = {"gold": 4500,
#               "silver": 3500,
#               "bronze": 2500,
#               "iron": 1500}

#this is where you define the MMR thresholds for each rank
def getRank(mmr: int):
    return("Ranked")
# def getRank(mmr: int):
#     if mmr >= 11500:
#         return("Grandmaster")
#     elif mmr >= 10000:
#         return("Master")
#     elif mmr >= 9000:
#         return("Diamond")
#     elif mmr >= 8000:
#         return("Pearl")
#     elif mmr >= 7000:
#         return("Emerald")
#     elif mmr >= 6000:
#         return("Ruby")
#     elif mmr >= 5000:
#         return("Sapphire")
#     elif mmr >= 4000:
#         return("Platinum")
#     elif mmr >= 3000:
#         return("Gold")
#     elif mmr >= 2000:
#         return("Silver")
#     elif mmr >= 1000:
#         return("Bronze")
#     else:
#         return ("Iron")

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

