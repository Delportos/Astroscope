from scenes import loading, galesplash, splash
import time

_phase = 'gale'
_loops_done = 0
_gale_started = None

def render():
    global _phase, _loops_done, _gale_started

    if _phase == 'gale':
        if _gale_started is None:
            _gale_started = time.time()
        img, _ = galesplash.render()
        if time.time() - _gale_started > 5.0:
            _phase = 'load'
        return img, 0.1

    if _phase == 'load':
        img, delay = loading.render()
        if loading._idx % len(loading._frames) == 0:
            _loops_done += 1
        if _loops_done >= 4:
            _phase = 'done'
        return img, delay

    # 'done' phase — show splash, hold forever
    return splash.render()[0], None
