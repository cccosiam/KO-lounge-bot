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

#first value is where the name goes, second is where the penalty amount goes
pen_cols = [3, 4]
pen_row = 92
pen_channel = 1515391220782727238
#first cell is the start of the range, second is end of the range
get_strike_info = ["E92", "M92"]

#cell that outputs raw stats string
stats_cell = "I20"

#yeah well
profanity_whitelist = ["pee", "ass", "scum", "cumber", "nig", "night", "dink", "dinks", "drunk", "dummy", "sucker", "suck", "fart", "gae", "gai", "god", "hell", "hump", "kill", "kum", "len", "lez", "lmao", "lmfao", "loin", "lust", "maxi", "muff", "muffin", "dickens", "nad", "nads", "nob", "omg", "coral", "pawn", "spoon", "pot", "grape", "drape", "rum", "grump", "sob", "spice", "spicy", "steamy", "tit", "titi", "tush", "ugly", "urine", "uzi", "vag", "wad", "wop", "xx"]
profanity_blacklist = []

#names of the knockout rallies. can be updated if they add more
rallies = {
    "Golden": "<:rally01golden:1495475155496079432>",
    "Ice": "<:rally02ice:1495475318583066794>",
    "Moon": "<:rally03moon:1495475373352292464>",
    "Spiny": "<:rally04spiny:1495482735941259396>",
    "Cherry": "<:rally05cherry:1495483655735214313>",
    "Acorn": "<:rally06acorn:1495481302512701631>",
    "Cloud": "<:rally07cloud:1495481609980481866>",
    "Heart": "<:rally08heart:1495483365627924661>",
    "Drill": "<:rally09drill:1523251786259890176>",
    "Boomerang": "<:rally10boomerang:1523251808053624873>"
}

#relevant channels
key_channels = {
    "verify": 1509691402731258056,
    "penalty_log": 1515086211793027255,
    "mmr_reduction_log": 1518249924964126844,
    "verification_log": 1517325041128177818,
    "updating_log": 1516856492677140642,
    "staff_pings": 1518341565482012804,
    "name_change_request": 1515137713622487190,
    "name_change_log": 1516856324028109030,
    "pending_verification": 1519780153784271000,
    "tier-all": 1488615764649971783
}

#general channels
general_channels = {
    "general": 1475608139708764316,
    "media": 1488631499384295486,
    "bots": 1514433224712130711,
    "war_chat": 1515137548836536430,
    "strat_discussion": 1519064517726834738
}

#key roles
key_roles = {
    "player": 1475614507781984496,
    "lounge_staff": 1488275316097941525,
    "chat_restricted": 1515768015617003644,
    "muted": 1515769177783271465
}

#preseason only uses one tier so every other tier is commented out
#when it's time for tiers, use other dictionary
channels = {"ALL": 1509676638865063987}
#id of the results channels for each tier
# channels = {"X": 1494770846701719582,
#             "S": 1494770892050534440,
#             "A": 1494770925412024573,
#             "B": 1494771093775581366,
#             "C": 1494771093775581366,
#             "D": 1494771160749965446,
#             "E": 1494771201401163857,
#             "F": 1494771307328569577,
#             "SQ": 1488615812481810542}

#contains the emoji ID and role ID for each rank in the server;
#rank names should match up with getRank function below
ranks = {"Ranked": {
    "emoji": "<:dashfood:1495474890772447352>",
    "roleid": 1488633685342290001}}
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

