import json

from hearthstone.enums import GameTag, BlockType
from hslog import LogParser
from hslog.packets import *


LOG_FILE = "logs/Power2.log"
CARD_DB_FILE = "resources/cards.json"

MY_BTAG = "Pomi#21780"

# Card overrides for cards missing from HearthstoneJSON
CARD_NAME_OVERRIDES = {
    "BG20_GEM": "Blood Gem",
}

CARD_TYPE_OVERRIDES = {
    "BG20_GEM": "SPELL",
}

ALLOWED_HAND_TYPES = {"MINION", "BATTLEGROUND_SPELL", "SPELL"}
GENERATED_HAND_CARDS = {"BG20_GEM"}

SELL_CARD_ID = "TB_BaconShop_DragSell"


# Runtime state
my_player_id = None
current_turn = None

entity_db = {}
entity_controller = {}
entity_zone = {}

hand = []
board = []

card_names = {}
card_types = {}

played_spells = set()
pending_generated_cards = []


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
    global my_player_id

    if isinstance(packet, CreateGame):
        print("=== New Game ===")
        return

    if isinstance(packet, FullEntity):
        handle_full_entity(packet)
        return

    if isinstance(packet, ShowEntity):
        handle_show_entity(packet)
        return

    if isinstance(packet, TagChange):
        handle_tag_change(packet, active_block_card, active_player_id)
        return

    if isinstance(packet, Block):
        handle_block(packet)
        return


def handle_full_entity(packet):
    entity_db[packet.entity] = packet.card_id

    if is_generated_hand_card(packet.card_id):
        add_generated_card_to_hand(packet.entity)


def handle_show_entity(packet):
    entity_db[packet.entity] = packet.card_id


def handle_tag_change(packet, active_block_card=None, active_player_id=None):
    global current_turn

    if packet.tag == GameTag.CONTROLLER:
        entity_controller[packet.entity] = int(packet.value)
        return

    if packet.tag == GameTag.TURN:
        entity = packet.entity

        if hasattr(entity, "player_id") and entity.player_id == my_player_id:
            if packet.value != current_turn:
                if current_turn is not None:
                    flush_pending_generated_cards()
                    print_state()

                current_turn = packet.value
                print(f"\n=== TURN {current_turn} ===")

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

    if owner != my_player_id or not card_id:
        return

    if is_ignored_card(card_id):
        return

    # 1 = PLAY, 3 = HAND, 4 = DECK, 5 = GRAVEYARD, 6 = REMOVEDFROMGAME
    if new_zone == 3:
        add_card_to_hand(packet.entity, card_id)
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
    if my_player_id is None:
        return

    card_id = entity_db.get(packet.entity)

    if not card_id:
        return

    if is_spell_from_hand(packet.entity, card_id):
        play_spell_from_hand(packet, card_id)
        return

    controller = entity_controller.get(packet.entity)

    if controller == my_player_id and not is_ignored_card(card_id):
        print(f"🛒 You bought: {get_card_name(card_id)} [{get_card_type(card_id)}]")


def add_card_to_hand(entity_id, card_id):
    if get_card_type(card_id) not in ALLOWED_HAND_TYPES:
        return

    if entity_id not in hand:
        hand.append(entity_id)
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
    if active_block_card != SELL_CARD_ID:
        return

    if entity_id in board:
        board.remove(entity_id)
        print(f"💰 Sold: {get_card_name(card_id)}")
        flush_pending_generated_cards()


def flush_pending_generated_cards():
    for entity_id in pending_generated_cards:
        card_id = entity_db.get(entity_id)

        if card_id:
            print(f"✋ Generated to hand: {get_card_name(card_id)}")

    pending_generated_cards.clear()


def print_state():
    print("📌 Hand:", [
        get_card_name(entity_db.get(entity_id, "UNKNOWN"))
        for entity_id in hand
    ])

    print("🧱 Board:", [
        get_card_name(entity_db.get(entity_id, "UNKNOWN"))
        for entity_id in board
        if get_card_type(entity_db.get(entity_id, "UNKNOWN")) == "MINION"
    ])


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


def get_card_name(card_id):
    return CARD_NAME_OVERRIDES.get(card_id) or card_names.get(card_id, card_id)


def get_card_type(card_id):
    return CARD_TYPE_OVERRIDES.get(card_id) or card_types.get(card_id, "UNKNOWN")


def get_entity_id(entity):
    if isinstance(entity, int):
        return entity

    if hasattr(entity, "entity_id"):
        return entity.entity_id

    return entity


def get_entity_owner(entity_id, active_player_id=None):
    controller = entity_controller.get(entity_id)

    if controller is not None:
        return controller

    return active_player_id


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


if __name__ == "__main__":
    main()