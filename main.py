import json

from hearthstone.enums import GameTag, BlockType
from hslog import LogParser
from hslog.packets import *


LOG_FILE = "logs/Power2.log"
CARD_DB_FILE = "resources/cards.json"
MY_BTAG = "Pomi#21780"

CARD_NAME_OVERRIDES = {
    "BG20_GEM": "Blood Gem",
}

CARD_TYPE_OVERRIDES = {
    "BG20_GEM": "SPELL",
}

ALLOWED_HAND_TYPES = {"MINION", "BATTLEGROUND_SPELL", "SPELL"}
GENERATED_HAND_CARDS = {"BG20_GEM"}

SELL_CARD_ID = "TB_BaconShop_DragSell"
REROLL_CARD_ID = "TB_BaconShop_8p_Reroll_Button"
FREEZE_CARD_ID = "TB_BaconShopLockAll_Button"
DRAG_BUY_SPELL_ID = "TB_BaconShop_DragBuy_Spell"
TECH_UP_PREFIX = "TB_BaconShopTechUp"

BUY_COST = 3
ROLL_COST = 1
SELL_GAIN = 1


my_player_id = None
current_turn = None
current_gold = 0

entity_db = {}
entity_controller = {}
entity_zone = {}
entity_position = {}
entity_cost = {}
entity_creator = {}

card_names = {}
card_types = {}
card_costs = {}

hand = []
board = []

bought_entities = set()
generated_entities = set()
played_spells = set()
pending_generated_cards = []

hero_choices = []
selected_hero = None
hero_power_entity_id = None
hero_power_card_id = None

pending_choices = {}


def main():
    print("=== Parsing started ===\n")

    load_card_db()

    parser = LogParser()

    with open(LOG_FILE, "r", encoding="utf-8") as f:
        parser.read(f)

    if not parser.games:
        print("No games found.")
        return

    game = parser.games[0]

    print(f"Root packet: {type(game).__name__}")
    print(f"Child packets: {len(game.packets)}\n")

    for packet, active_block_card, active_player_id in walk_packets(game):
        handle_packet(packet, active_block_card, active_player_id)

    flush_pending_generated_cards()

    print(f"\nMy player_id = {my_player_id}")
    print_state()


def handle_packet(packet, active_block_card=None, active_player_id=None):
    if isinstance(packet, CreateGame):
        print("=== New Game ===")
        return

    if isinstance(packet, FullEntity):
        handle_full_entity(packet)
        return

    if isinstance(packet, ShowEntity):
        handle_show_entity(packet)
        return

    if type(packet).__name__ == "Choices":
        handle_choices(packet)
        return

    if type(packet).__name__ == "SendChoices":
        handle_send_choices(packet)
        return

    if isinstance(packet, TagChange):
        handle_tag_change(packet, active_block_card, active_player_id)
        return

    if isinstance(packet, Block):
        handle_block(packet)
        return


def handle_full_entity(packet):
    entity_db[packet.entity] = packet.card_id
    apply_entity_tags(packet.entity, packet.tags)
    detect_hero_power(packet.entity, packet.card_id)

    if is_generated_hand_card(packet.card_id):
        add_generated_card_to_hand(packet.entity)

    card_id = packet.card_id

    if not card_id:
        return

    controller = entity_controller.get(packet.entity)
    zone = entity_zone.get(packet.entity)
    creator_card_id = get_creator_card_id(packet.entity)

    if controller == my_player_id and zone == 3:
        if creator_card_id and not creator_card_id.startswith("TB_BaconShop"):
            generated_entities.add(packet.entity)

        add_card_to_hand(packet.entity, card_id, creator_card_id)


def handle_show_entity(packet):
    entity_db[packet.entity] = packet.card_id
    detect_hero_power(packet.entity, packet.card_id)


def handle_tag_change(packet, active_block_card=None, active_player_id=None):
    global current_turn, current_gold

    if packet.tag == GameTag.CONTROLLER:
        entity_controller[packet.entity] = int(packet.value)
        return

    if packet.tag == GameTag.COST:
        entity_cost[packet.entity] = int(packet.value)
        return

    if packet.tag == GameTag.ZONE_POSITION:
        entity_position[packet.entity] = int(packet.value)
        return

    if packet.tag == GameTag.TURN:
        entity = packet.entity

        if hasattr(entity, "player_id") and entity.player_id == my_player_id:
            if packet.value != current_turn:
                if current_turn is not None:
                    flush_pending_generated_cards()
                    print_state()

                current_turn = packet.value
                current_gold = get_start_gold(current_turn)

                print(f"\n=== TURN {current_turn} ===")
                print(f"💰 Start gold: {current_gold}")

        return

    if packet.tag == GameTag.ZONE:
        handle_zone_change(packet, active_block_card, active_player_id)
        return


def handle_zone_change(packet, active_block_card=None, active_player_id=None):
    old_zone = entity_zone.get(packet.entity)
    new_zone = int(packet.value)

    entity_zone[packet.entity] = new_zone

    card_id = entity_db.get(packet.entity)
    owner = get_entity_owner(packet.entity, active_player_id)

    if card_id and is_hero_card(card_id):
        handle_hero_zone(card_id, new_zone)
        return

    if owner != my_player_id or not card_id:
        return

    if is_ignored_card(card_id):
        return

    if new_zone == 3:
        add_card_to_hand(packet.entity, card_id, active_block_card)
        return

    if is_generated_spell_played(packet.entity, card_id, new_zone):
        hand.remove(packet.entity)
        print(f"✨ Played generated spell: {get_card_name(card_id)}")
        return

    if old_zone == 3 and new_zone == 1:
        play_card_from_hand(packet.entity, card_id)
        return

    if old_zone == 1 and new_zone in (5, 6):
        handle_possible_sell(packet.entity, card_id, active_block_card)
        return


def handle_block(packet):
    global my_player_id

    if my_player_id is None and hasattr(packet.entity, "name"):
        if packet.entity.name == MY_BTAG:
            my_player_id = packet.entity.player_id
            print(f"🎯 My player_id detected from BLOCK: {my_player_id}")

    if packet.type == BlockType.PLAY:
        handle_play_block(packet)


def handle_play_block(packet):
    global current_gold

    if my_player_id is None:
        return

    card_id = entity_db.get(packet.entity)

    if not card_id:
        return

    if packet.entity == hero_power_entity_id:
        handle_hero_power(packet)
        return

    if card_id == REROLL_CARD_ID:
        cost = get_action_cost(packet.entity, ROLL_COST)
        current_gold -= cost
        print(f"🔄 Rolled tavern (-{cost}), 💰 gold: {current_gold}")
        return

    if card_id == FREEZE_CARD_ID:
        print("❄️ Froze tavern")
        return

    if card_id.startswith(TECH_UP_PREFIX):
        level = get_tavern_upgrade_level(card_id)
        cost = get_action_cost(packet.entity, 0)
        current_gold -= cost
        print(f"⬆️ Upgraded tavern to {level} (-{cost}), 💰 gold: {current_gold}")
        return

    if card_id == DRAG_BUY_SPELL_ID:
        handle_spell_purchase(packet)
        return

    if is_spell_from_hand(packet.entity, card_id):
        play_spell_from_hand(packet, card_id)
        return

    if packet.entity in generated_entities:
        return

    controller = entity_controller.get(packet.entity)

    if controller == my_player_id and not is_ignored_card(card_id):
        bought_entities.add(packet.entity)

        cost = get_action_cost(packet.entity, BUY_COST)
        current_gold -= cost

        print(
            f"🛒 You bought: {get_card_name(card_id)} "
            f"[{get_card_type(card_id)}] (-{cost}), 💰 gold: {current_gold}"
        )


def handle_spell_purchase(packet):
    global current_gold

    target = get_entity_id(getattr(packet, "target", None))
    target_card_id = entity_db.get(target)

    bought_entities.add(target)

    cost = get_action_cost(packet.entity, BUY_COST)
    current_gold -= cost

    if target_card_id:
        print(
            f"🛒 You bought spell: {get_card_name(target_card_id)} "
            f"(-{cost}), 💰 gold: {current_gold}"
        )
    else:
        print(f"🛒 You bought spell (-{cost}), 💰 gold: {current_gold}")


def add_card_to_hand(entity_id, card_id, source_card_id=None):
    if get_card_type(card_id) not in ALLOWED_HAND_TYPES:
        return

    if entity_id in hand:
        return

    hand.append(entity_id)

    if source_card_id and source_card_id.startswith("TB_BaconShop"):
        return

    if source_card_id:
        print(
            f"🎁 Received from {get_card_name(source_card_id)}: "
            f"{get_card_name(card_id)}"
        )
    else:
        print(f"✋ Added to hand: {get_card_name(card_id)}")


def add_generated_card_to_hand(entity_id):
    if current_turn is None:
        return

    if entity_id not in hand:
        hand.append(entity_id)
        pending_generated_cards.append(entity_id)


def play_card_from_hand(entity_id, card_id):
    if entity_id in hand:
        hand.remove(entity_id)

    if get_card_type(card_id) == "MINION":
        if entity_id not in board:
            board.append(entity_id)
            print(f"🧩 Played to board: {get_card_name(card_id)}")
    else:
        if entity_id not in played_spells:
            print(f"✨ Played spell/card: {get_card_name(card_id)} [{get_card_type(card_id)}]")


def play_spell_from_hand(packet, card_id):
    hand.remove(packet.entity)
    played_spells.add(packet.entity)

    target = get_entity_id(getattr(packet, "target", None))
    target_card_id = entity_db.get(target)

    if target_card_id:
        print(f"✨ Played spell: {get_card_name(card_id)} → {get_card_name(target_card_id)}")
    else:
        print(f"✨ Played spell: {get_card_name(card_id)}")


def handle_possible_sell(entity_id, card_id, active_block_card):
    global current_gold

    if active_block_card != SELL_CARD_ID:
        return

    if entity_id in board:
        board.remove(entity_id)
        current_gold += SELL_GAIN

        print(f"💰 Sold: {get_card_name(card_id)} (+{SELL_GAIN}), 💰 gold: {current_gold}")
        flush_pending_generated_cards()


def flush_pending_generated_cards():
    for entity_id in pending_generated_cards:
        card_id = entity_db.get(entity_id)

        if card_id:
            print(f"✋ Generated to hand: {get_card_name(card_id)}")

    pending_generated_cards.clear()


def print_state():
    board_entities = [
        entity_id for entity_id in board
        if get_card_type(entity_db.get(entity_id, "UNKNOWN")) == "MINION"
    ]

    board_entities.sort(key=lambda e: entity_position.get(e, 999))

    print("📌 Hand:", [
        get_card_name(entity_db.get(entity_id, "UNKNOWN"))
        for entity_id in hand
    ])

    print("🧱 Board:", [
        get_card_name(entity_db.get(entity_id, "UNKNOWN"))
        for entity_id in board_entities
    ])


def handle_hero_zone(card_id, new_zone):
    if selected_hero is not None:
        return

    if new_zone in (3, 4):
        add_hero_choice(card_id)

    elif new_zone == 1 and card_id in hero_choices:
        set_selected_hero(card_id)


def add_hero_choice(card_id):
    if selected_hero is not None:
        return

    if len(hero_choices) >= 4:
        return

    if card_id not in hero_choices:
        hero_choices.append(card_id)
        print(f"🧙 Hero offered: {get_card_name(card_id)}")


def set_selected_hero(card_id):
    global selected_hero

    selected_hero = card_id
    print(f"✅ Selected hero: {get_card_name(card_id)}")


def detect_hero_power(entity_id, card_id):
    global hero_power_entity_id, hero_power_card_id

    if not card_id:
        return

    if hero_power_entity_id is not None:
        return

    if card_id.startswith("TB_BaconShop_HP_"):
        hero_power_entity_id = entity_id
        hero_power_card_id = card_id
        print(f"🦸 Hero power detected: {get_card_name(card_id)}")


def handle_hero_power(packet):
    global current_gold

    log_cost = entity_cost.get(packet.entity)
    db_cost = get_card_cost(hero_power_card_id, fallback=0)

    cost = log_cost if log_cost is not None else db_cost
    current_gold -= cost

    target = get_entity_id(getattr(packet, "target", None))
    target_card_id = entity_db.get(target)

    if target and target_card_id:
        print(
            f"🦸 Used hero power: {get_card_name(hero_power_card_id)} "
            f"→ {get_card_name(target_card_id)} "
            f"(-{cost}), 💰 gold: {current_gold}"
        )
    else:
        print(
            f"🦸 Used hero power: {get_card_name(hero_power_card_id)} "
            f"(-{cost}), 💰 gold: {current_gold}"
        )


def handle_choices(packet):
    if not hasattr(packet.entity, "player_id"):
        return

    if packet.entity.player_id != my_player_id:
        return

    pending_choices[packet.id] = packet.choices

    print("🔎 Discover options:")

    for index, entity_id in enumerate(packet.choices, start=1):
        card_id = entity_db.get(entity_id)
        print(f"   {index}. {get_card_name(card_id)}")


def handle_send_choices(packet):
    choice_options = pending_choices.get(packet.id)

    if not choice_options:
        return

    for chosen_entity in packet.choices:
        card_id = entity_db.get(chosen_entity)
        print(f"✅ Chose: {get_card_name(card_id)}")

    pending_choices.pop(packet.id, None)


def walk_packets(packet, active_block_card=None, active_player_id=None):
    if isinstance(packet, Block):
        block_card = entity_db.get(packet.entity)

        if block_card:
            active_block_card = block_card

        if hasattr(packet.entity, "player_id"):
            active_player_id = packet.entity.player_id
        else:
            controller = entity_controller.get(packet.entity)

            if controller is not None:
                active_player_id = controller

    yield packet, active_block_card, active_player_id

    if hasattr(packet, "packets"):
        for child in packet.packets:
            yield from walk_packets(child, active_block_card, active_player_id)


def apply_entity_tags(entity_id, tags):
    for tag, value in tags:
        if tag == GameTag.CONTROLLER:
            entity_controller[entity_id] = int(value)

        elif tag == GameTag.ZONE:
            entity_zone[entity_id] = int(value)

        elif tag == GameTag.ZONE_POSITION:
            entity_position[entity_id] = int(value)

        elif tag == GameTag.COST:
            entity_cost[entity_id] = int(value)

        elif tag == GameTag.CREATOR:
            entity_creator[entity_id] = int(value)


def load_card_db():
    with open(CARD_DB_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    for card in data:
        card_id = card.get("id")

        if not card_id:
            continue

        if "name" in card:
            card_names[card_id] = card["name"]

        if "type" in card:
            card_types[card_id] = card["type"]

        if "cost" in card:
            card_costs[card_id] = card["cost"]


def get_card_name(card_id):
    return CARD_NAME_OVERRIDES.get(card_id) or card_names.get(card_id, card_id)


def get_card_type(card_id):
    return CARD_TYPE_OVERRIDES.get(card_id) or card_types.get(card_id, "UNKNOWN")


def get_card_cost(card_id, fallback=0):
    return card_costs.get(card_id, fallback)


def get_action_cost(entity_id, fallback=0):
    return entity_cost.get(entity_id, fallback)


def get_start_gold(turn):
    return min(turn + 2, 10)


def get_entity_id(entity):
    if isinstance(entity, int):
        return entity

    if hasattr(entity, "entity_id"):
        return entity.entity_id

    return entity


def get_entity_owner(entity_id, active_player_id=None):
    return entity_controller.get(entity_id, active_player_id)


def get_creator_card_id(entity_id):
    creator_entity = entity_creator.get(entity_id)

    if creator_entity is None:
        return None

    return entity_db.get(creator_entity)


def get_tavern_upgrade_level(card_id):
    for level in range(2, 7):
        if f"TechUp0{level}" in card_id:
            return level

    return "?"


def is_generated_hand_card(card_id):
    return card_id in GENERATED_HAND_CARDS and current_turn is not None


def is_ignored_card(card_id):
    return card_id.startswith("TB_BaconShop")


def is_generated_spell_played(entity_id, card_id, new_zone):
    return (
        entity_id in hand
        and get_card_type(card_id) == "SPELL"
        and new_zone in (1, 4, 5)
    )


def is_spell_from_hand(entity_id, card_id):
    return entity_id in hand and get_card_type(card_id) != "MINION"


def is_hero_card(card_id):
    return get_card_type(card_id) == "HERO"


if __name__ == "__main__":
    main()