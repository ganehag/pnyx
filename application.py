#!/usr/bin/python3
import sys, os

sys.path.insert(1, os.path.join(sys.path[0], 'src'))

import main

def create_app():
  return main.app

if __name__ == '__main__':
    if "--setup" in sys.argv:
        main.database.create_tables([main.Comment,
                                     main.User,
                                     main.Community,
                                     main.CommunityUser,
                                     main.Proposal,
                                     main.CommentVote,
                                     main.PostVote])
        print("Database tables created")

    else:
        main.app.run(host='0.0.0.0', port=8080, debug=True, threaded=True)

