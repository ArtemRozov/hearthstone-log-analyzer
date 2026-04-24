from hearthstone.enums import GameTag, BlockType
from hslog import LogParser
from hslog.packets import *

LOG_FILE = "logs/Power2.log"

MY_BTAG = "Pomi#21780"

my_player_id = None
entity_db = {}
entity_controller = {}
current_turn = None


def main():
    print("=== Parsing started ===\n")

    with open(LOG_FILE, "r", encoding="utf-8") as f:
        parser = LogParser()
        parser.read(f)

    if not parser.games:
        print("No games found.")
        return

    game = parser.games[0]

    print(f"Root packet: {type(game).__name__}")
    print(f"Child packets: {len(game.packets)}\n")

    for packet in walk_packets(game):
        handle_packet(packet)

    print(f"\nMy player_id = {my_player_id}")


def handle_packet(packet):
    global my_player_id
    global current_turn

    if isinstance(packet, CreateGame):
        print("=== New Game ===")

    elif isinstance(packet, FullEntity):
        entity_db[packet.entity] = packet.card_id
       # print(f"[FULL] id={packet.entity} card={packet.card_id}")

    elif isinstance(packet, ShowEntity):
        entity_db[packet.entity] = packet.card_id
      #  print(f"[SHOW] id={packet.entity} card={packet.card_id}")

    elif isinstance(packet, TagChange):
        if packet.tag == GameTag.CONTROLLER:
            entity_controller[packet.entity] = int(packet.value)

        elif packet.tag == GameTag.TURN:
            entity = packet.entity
            if hasattr(entity, "player_id") and entity.player_id == my_player_id:
                if packet.value != current_turn:
                    current_turn = packet.value
                    print(f"\n=== TURN {current_turn} ===")

        #elif packet.tag == GameTag.STEP:
            # print(f"[STEP] {packet.value}")

        #elif packet.tag == GameTag.ZONE:
            # print(f"[ZONE] entity={packet.entity} -> {packet.value}")

    elif isinstance(packet, Block):
        if my_player_id is None and hasattr(packet.entity, "name"):
            if packet.entity.name == MY_BTAG:
                my_player_id = packet.entity.player_id
                print(f"🎯 My player_id detected from BLOCK: {my_player_id}")

        if packet.type == BlockType.PLAY:
            if my_player_id is None:
                return

            controller = entity_controller.get(packet.entity)

            if controller == my_player_id:
                card_id = entity_db.get(packet.entity)

                if card_id and not card_id.startswith("TB_BaconShop"):
                    print(f"🛒 You bought: {card_id}")


def walk_packets(packet):
    yield packet

    if hasattr(packet, "packets"):
        for child in packet.packets:
            yield from walk_packets(child)


if __name__ == "__main__":
    main()