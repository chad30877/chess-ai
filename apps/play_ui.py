
"""Pygame chess demo entrypoint and compatible replay helpers."""

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import chess
import pygame

from engine.replay.replay_loader import load_replay_json
from engine.replay.replay_session import ReplaySession
from engine.game import create_board, get_legal_moves, make_move
from ui.board_view import BOARD_PIXELS, BoardView, WINDOW_HEIGHT
from ui.move_list_view import MOVE_LIST_WIDTH, MoveListView
from ui.replay_info_view import INFO_PANEL_HEIGHT, ReplayInfoView

WINDOW_TITLE = "Chess AI"
SAMPLE_REPLAY = {
    "initial_fen": chess.STARTING_FEN,
    "moves_uci": ["e2e4", "e7e5", "g1f3", "b8c6", "f1c4", "g8f6"],
    "result": "*",
    "metadata": {},
}


def get_replay_data(replay_path: str | None) -> dict:
    if replay_path is not None:
        return load_replay_json(replay_path)
    return SAMPLE_REPLAY.copy()


def build_move_items(initial_fen: str, moves_uci: list[str]) -> list[dict]:
    board = create_board(initial_fen)
    move_items: list[dict] = []

    for ply, move_uci in enumerate(moves_uci, start=1):
        move = chess.Move.from_uci(move_uci)
        if move not in get_legal_moves(board):
            raise ValueError(f"Illegal move while building move list: {move_uci}")

        side = "w" if board.turn == chess.WHITE else "b"
        move_no = board.fullmove_number
        san = board.san(move)

        move_items.append(
            {
                "ply": ply,
                "move_no": move_no,
                "side": side,
                "uci": move_uci,
                "san": san,
            }
        )

        make_move(board, move)

    return move_items


def build_replay_info(replay_data: dict) -> dict[str, str]:
    metadata = replay_data.get("metadata", {})
    return {
        "white_player": str(metadata.get("white_player", "White")),
        "black_player": str(metadata.get("black_player", "Black")),
        "result": str(replay_data.get("result", "*")),
        "game_id": str(metadata.get("game_id", "-")),
    }


def sync_displayed_ply(
    move_list_view: MoveListView,
    move_items: list[dict],
    new_ply: int,
) -> int:
    move_list_view.ensure_ply_visible(move_items, new_ply)
    return new_ply


def goto_ply(
    session: ReplaySession,
    move_list_view: MoveListView,
    move_items: list[dict],
    target_ply: int,
) -> int:
    session.goto_ply(target_ply)
    return sync_displayed_ply(move_list_view, move_items, target_ply)


def step_prev(
    session: ReplaySession,
    move_list_view: MoveListView,
    move_items: list[dict],
    displayed_ply: int,
) -> int:
    session.prev()
    return sync_displayed_ply(move_list_view, move_items, max(0, displayed_ply - 1))


def step_next(
    session: ReplaySession,
    move_list_view: MoveListView,
    move_items: list[dict],
    displayed_ply: int,
    total_ply: int,
) -> int:
    session.next()
    return sync_displayed_ply(
        move_list_view,
        move_items,
        min(total_ply, displayed_ply + 1),
    )


def goto_first(
    session: ReplaySession,
    move_list_view: MoveListView,
    move_items: list[dict],
) -> int:
    session.first()
    return sync_displayed_ply(move_list_view, move_items, 0)


def goto_last(
    session: ReplaySession,
    move_list_view: MoveListView,
    move_items: list[dict],
    total_ply: int,
) -> int:
    session.last()
    return sync_displayed_ply(move_list_view, move_items, total_ply)


def handle_mouse_button_down(
    event: pygame.event.Event,
    move_list_view: MoveListView,
    move_items: list[dict],
    session: ReplaySession,
    displayed_ply: int,
) -> int:
    if event.button == 1:
        dragging_started = move_list_view.handle_mouse_down(event.pos, move_items)
        if not dragging_started:
            target_ply = move_list_view.handle_click(event.pos)
            if target_ply is not None:
                return goto_ply(session, move_list_view, move_items, target_ply)
        return displayed_ply

    if event.button == 4:
        move_list_view.handle_wheel(event.pos, 1, move_items)
    elif event.button == 5:
        move_list_view.handle_wheel(event.pos, -1, move_items)

    return displayed_ply


def handle_mouse_button_up(event: pygame.event.Event, move_list_view: MoveListView) -> None:
    if event.button == 1:
        move_list_view.handle_mouse_up()


def handle_mouse_motion(
    event: pygame.event.Event,
    move_list_view: MoveListView,
    move_items: list[dict],
) -> None:
    move_list_view.handle_mouse_motion(event.pos, move_items)


def handle_mouse_wheel(
    event: pygame.event.Event,
    move_list_view: MoveListView,
    move_items: list[dict],
) -> None:
    move_list_view.handle_wheel(pygame.mouse.get_pos(), event.y, move_items)


def handle_keydown(
    event: pygame.event.Event,
    session: ReplaySession,
    move_list_view: MoveListView,
    move_items: list[dict],
    displayed_ply: int,
    total_ply: int,
    is_flipped: bool,
) -> tuple[int, bool]:
    if event.key == pygame.K_LEFT:
        return step_prev(session, move_list_view, move_items, displayed_ply), is_flipped
    if event.key == pygame.K_RIGHT:
        return (
            step_next(
                session,
                move_list_view,
                move_items,
                displayed_ply,
                total_ply,
            ),
            is_flipped,
        )
    if event.key == pygame.K_HOME:
        return goto_first(session, move_list_view, move_items), is_flipped
    if event.key == pygame.K_END:
        return goto_last(session, move_list_view, move_items, total_ply), is_flipped
    if event.key == pygame.K_f:
        return displayed_ply, not is_flipped

    return displayed_ply, is_flipped


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Launch the chess home screen or open a replay.")
    parser.add_argument(
        "--replay",
        type=str,
        default=None,
        help="Path to a replay JSON file. Suggested location: data/replays/",
    )
    return parser.parse_args()


def prepare_replay_content(replay_path: str | None) -> tuple[dict, list[dict], dict[str, str]]:
    replay_data = get_replay_data(replay_path)
    move_items = build_move_items(replay_data["initial_fen"], replay_data["moves_uci"])
    replay_info = build_replay_info(replay_data)
    return replay_data, move_items, replay_info


def create_pygame_context() -> tuple[pygame.Surface, pygame.time.Clock]:
    pygame.init()
    screen = pygame.display.set_mode((BOARD_PIXELS + MOVE_LIST_WIDTH, WINDOW_HEIGHT))
    pygame.display.set_caption(WINDOW_TITLE)
    clock = pygame.time.Clock()
    return screen, clock


def create_views(screen: pygame.Surface) -> tuple[BoardView, ReplayInfoView, MoveListView]:
    board_view = BoardView(screen)
    replay_info_view = ReplayInfoView(screen, origin_x=BOARD_PIXELS, origin_y=0)
    move_list_view = MoveListView(
        screen,
        origin_x=BOARD_PIXELS,
        origin_y=INFO_PANEL_HEIGHT,
        height=WINDOW_HEIGHT - INFO_PANEL_HEIGHT,
    )
    return board_view, replay_info_view, move_list_view


def create_session(replay_data: dict) -> tuple[ReplaySession, int]:
    session = ReplaySession(
        replay_data["initial_fen"], replay_data["moves_uci"],
        claim_draw=replay_data.get("metadata", {}).get("rules", {}).get("claim_draw", False),
    )
    return session, session.total_ply()

def handle_frame_events(
    session: ReplaySession,
    move_list_view: MoveListView,
    move_items: list[dict],
    displayed_ply: int,
    total_ply: int,
    is_flipped: bool,
) -> tuple[bool, int, bool]:
    running = True

    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False
        elif event.type == pygame.MOUSEBUTTONDOWN:
            displayed_ply = handle_mouse_button_down(
                event,
                move_list_view,
                move_items,
                session,
                displayed_ply,
            )
        elif event.type == pygame.MOUSEBUTTONUP:
            handle_mouse_button_up(event, move_list_view)
        elif event.type == pygame.MOUSEMOTION:
            handle_mouse_motion(event, move_list_view, move_items)
        elif event.type == pygame.MOUSEWHEEL:
            handle_mouse_wheel(event, move_list_view, move_items)
        elif event.type == pygame.KEYDOWN:
            displayed_ply, is_flipped = handle_keydown(
                event,
                session,
                move_list_view,
                move_items,
                displayed_ply,
                total_ply,
                is_flipped,
            )

    return running, displayed_ply, is_flipped


def render_frame(
    session: ReplaySession,
    board_view: BoardView,
    replay_info_view: ReplayInfoView,
    move_list_view: MoveListView,
    replay_info: dict[str, str],
    move_items: list[dict],
    displayed_ply: int,
    total_ply: int,
    is_flipped: bool,
) -> None:
    board = session.current_board()
    board_view.render(
        board=board,
        current_ply=displayed_ply,
        total_ply=total_ply,
        is_flipped=is_flipped,
    )
    replay_info_view.render(replay_info)
    move_list_view.render(move_items, displayed_ply)
    pygame.display.flip()


def main() -> None:
    from apps.chess_application import APP_SIZE, ChessApplication

    args = parse_args()
    # Enable native pixels before SDL creates a window on Windows HiDPI displays.
    import sys
    if sys.platform == "win32":
        import ctypes
        try:
            ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        except (AttributeError, OSError):
            ctypes.windll.user32.SetProcessDPIAware()
    pygame.init()
    screen = pygame.display.set_mode(APP_SIZE, pygame.RESIZABLE)
    pygame.display.set_caption(WINDOW_TITLE)
    clock = pygame.time.Clock()
    app = ChessApplication(screen, args.replay)
    try:
        while app.running:
            app.render()
            pygame.display.flip()
            for event in pygame.event.get():
                app.handle_event(event)
            app.tick()
            clock.tick(60)
    finally:
        app.close()
        pygame.quit()


if __name__ == "__main__":
    main()
