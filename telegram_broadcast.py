from broadcasts import broadcast_daily, broadcast_reminders, broadcast_results
from commands import broadcast_heartbeat, process_commands
from live import process_live_updates
from sync import update_fixtures_from_json


def print_usage():
    print(
        "Usage: python3 telegram_broadcast.py "
        "[refresh|commands|live|daily|reminders|results|heartbeat]"
    )


if __name__ == '__main__':
    import sys

    if len(sys.argv) <= 1:
        print_usage()
    else:
        mode = sys.argv[1]
        if mode == 'refresh':
            update_fixtures_from_json()
        elif mode == 'commands':
            process_commands()
        elif mode == 'live':
            process_live_updates()
        elif mode == 'daily':
            broadcast_daily()
        elif mode == 'reminders':
            broadcast_reminders()
        elif mode == 'results':
            broadcast_results()
        elif mode == 'heartbeat':
            broadcast_heartbeat()
        else:
            print_usage()
