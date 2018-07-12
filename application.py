#!/usr/bin/python3
import sys, os

sys.path.insert(1, os.path.join(sys.path[0], 'src'))

import main

def create_app():
  return main.app

if __name__ == '__main__':
    if "--setup" in sys.argv:
        main.create_db_tables()
        print("Database tables created")

    else:
        main.app.run(host='0.0.0.0', port=8080, debug=True, threaded=True)

