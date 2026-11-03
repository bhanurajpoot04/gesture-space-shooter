"""
╔══════════════════════════════════════════════════════════════════════╗
║           🚀 GESTURE SPACE SHOOTER — OpenCV + MediaPipe             ║
╠══════════════════════════════════════════════════════════════════════╣
║  CONTROLS (No keyboard/mouse needed — use your HAND!):              ║
║  ✋ Move Hand  → Move spaceship left / right                        ║
║  ☝️  1 Finger  → SHOOT laser                                        ║
║  ✌️  2 Fingers → SHIELD (blocks one hit)                            ║
║  ✊  Fist      → PAUSE / RESUME                                      ║
╠══════════════════════════════════════════════════════════════════════╣
║  Install dependencies:                                               ║
║    pip install opencv-python mediapipe numpy                         ║
╚══════════════════════════════════════════════════════════════════════╝
"""

import cv2
import mediapipe as mp
import numpy as np
import random
import time
import math

# ─────────────────────────────────────────────
#  CONSTANTS & CONFIG
# ─────────────────────────────────────────────
WIN_W, WIN_H = 900, 700          # Game window size
CAM_W, CAM_H = 320, 240          # Camera feed size (shown in corner)

FPS_CAP       = 60
SHIP_SPEED    = 8
BULLET_SPEED  = 12
ENEMY_BASE_SP = 2.0
STAR_COUNT    = 120
MAX_LIVES     = 3
SHOOT_COOLDOWN = 0.25            # seconds between shots

# Colour palette (BGR)
C_BG          = (10, 5, 20)
C_STAR        = (200, 200, 230)
C_SHIP        = (0, 220, 255)
C_SHIP_DARK   = (0, 100, 180)
C_BULLET      = (0, 255, 180)
C_ENEMY_A     = (60,  80, 230)
C_ENEMY_B     = (30, 180, 255)
C_SHIELD      = (255, 200, 50)
C_EXPLOSION_A = (0,  160, 255)
C_EXPLOSION_B = (0,   80, 255)
C_HUD_ACCENT  = (0, 255, 200)
C_DANGER      = (50,  50, 255)
C_WHITE       = (255, 255, 255)
C_GREEN       = (50, 230, 80)
C_YELLOW      = (30, 230, 255)

# ─────────────────────────────────────────────
#  HELPERS
# ─────────────────────────────────────────────
def lerp(a, b, t):
    return a + (b - a) * t

def draw_glow(img, center, radius, color, alpha=0.5):
    """Draw a soft radial glow effect."""
    overlay = img.copy()
    cv2.circle(overlay, center, radius, color, -1)
    cv2.addWeighted(overlay, alpha, img, 1 - alpha, 0, img)

def draw_text_centered(img, text, y, font_scale, color, thickness=1, shadow=True):
    font = cv2.FONT_HERSHEY_DUPLEX
    (tw, th), _ = cv2.getTextSize(text, font, font_scale, thickness)
    x = (WIN_W - tw) // 2
    if shadow:
        cv2.putText(img, text, (x+2, y+2), font, font_scale, (0,0,0), thickness+1, cv2.LINE_AA)
    cv2.putText(img, text, (x, y), font, font_scale, color, thickness, cv2.LINE_AA)

def poly_points(cx, cy, n, r, angle_offset=0):
    pts = []
    for i in range(n):
        a = math.radians(360 / n * i + angle_offset)
        pts.append((int(cx + r * math.cos(a)), int(cy + r * math.sin(a))))
    return np.array(pts)

# ─────────────────────────────────────────────
#  STAR FIELD
# ─────────────────────────────────────────────
class Star:
    def __init__(self):
        self.reset(init=True)

    def reset(self, init=False):
        self.x = random.randint(0, WIN_W)
        self.y = random.randint(0, WIN_H) if init else 0
        self.speed = random.uniform(0.5, 3.5)
        self.size  = 1 if self.speed < 1.5 else (2 if self.speed < 2.5 else 3)
        self.bright = random.randint(100, 255)

    def update(self, level):
        self.y += self.speed * (1 + level * 0.05)
        if self.y > WIN_H:
            self.reset()

    def draw(self, frame):
        b = self.bright
        cv2.circle(frame, (int(self.x), int(self.y)), self.size, (b, b, b), -1)

# ─────────────────────────────────────────────
#  BULLET
# ─────────────────────────────────────────────
class Bullet:
    def __init__(self, x, y):
        self.x, self.y = x, y
        self.active = True
        self.trail   = []

    def update(self):
        self.trail.append((int(self.x), int(self.y)))
        if len(self.trail) > 8:
            self.trail.pop(0)
        self.y -= BULLET_SPEED
        if self.y < -10:
            self.active = False

    def draw(self, frame):
        # Trail
        for i, (tx, ty) in enumerate(self.trail):
            alpha = (i + 1) / len(self.trail)
            r = max(1, int(alpha * 3))
            brightness = int(alpha * 200)
            cv2.circle(frame, (tx, ty), r, (brightness, 255, int(brightness * 0.7)), -1)
        # Head
        draw_glow(frame, (int(self.x), int(self.y)), 8, C_BULLET, 0.3)
        cv2.circle(frame, (int(self.x), int(self.y)), 4, C_BULLET, -1)
        cv2.circle(frame, (int(self.x), int(self.y)), 2, C_WHITE, -1)

    def get_rect(self):
        return (self.x - 6, self.y - 6, 12, 12)

# ─────────────────────────────────────────────
#  ENEMY
# ─────────────────────────────────────────────
class Enemy:
    TYPES = ['A', 'B', 'C']

    def __init__(self, level):
        self.type   = random.choice(self.TYPES)
        self.size   = {'A': 28, 'B': 22, 'C': 36}[self.type]
        self.hp     = {'A': 1,  'B': 2,  'C': 3 }[self.type]
        self.points = {'A': 10, 'B': 20, 'C': 35}[self.type]
        self.x      = random.randint(self.size + 20, WIN_W - self.size - 20)
        self.y      = -self.size
        self.speed  = ENEMY_BASE_SP + level * 0.4 + random.uniform(-0.3, 0.5)
        self.drift  = random.uniform(-0.8, 0.8)
        self.angle  = 0
        self.active = True
        self.flash  = 0    # hit flash timer

    def update(self):
        self.y += self.speed
        self.x += self.drift
        self.x  = max(self.size, min(WIN_W - self.size, self.x))
        self.angle = (self.angle + 1.5) % 360
        if self.flash > 0:
            self.flash -= 1
        if self.y > WIN_H + self.size:
            self.active = False

    def hit(self):
        self.hp   -= 1
        self.flash = 6
        if self.hp <= 0:
            self.active = False
            return True
        return False

    def draw(self, frame):
        cx, cy = int(self.x), int(self.y)
        color = (C_ENEMY_B if self.flash % 2 == 0 else C_WHITE) if self.flash > 0 else (
            {'A': C_ENEMY_A, 'B': C_ENEMY_B, 'C': C_DANGER}[self.type])

        if self.type == 'A':
            pts = poly_points(cx, cy, 3, self.size, self.angle)
            cv2.fillPoly(frame, [pts], color)
            inner = poly_points(cx, cy, 3, self.size // 2, self.angle + 30)
            cv2.fillPoly(frame, [inner], C_SHIP_DARK)
        elif self.type == 'B':
            pts = poly_points(cx, cy, 4, self.size, self.angle)
            cv2.fillPoly(frame, [pts], color)
            cv2.circle(frame, (cx, cy), self.size // 3, C_SHIP_DARK, -1)
        else:
            pts = poly_points(cx, cy, 6, self.size, self.angle)
            cv2.fillPoly(frame, [pts], color)
            inner = poly_points(cx, cy, 6, self.size // 2, self.angle + 15)
            cv2.fillPoly(frame, [inner], (40, 10, 80))
            cv2.circle(frame, (cx, cy), 8, (0, 255, 255), -1)

    def get_rect(self):
        return (self.x - self.size, self.y - self.size, self.size * 2, self.size * 2)

# ─────────────────────────────────────────────
#  EXPLOSION PARTICLE
# ─────────────────────────────────────────────
class Particle:
    def __init__(self, x, y, color):
        self.x, self.y = float(x), float(y)
        angle    = random.uniform(0, 2 * math.pi)
        speed    = random.uniform(2, 8)
        self.vx  = math.cos(angle) * speed
        self.vy  = math.sin(angle) * speed
        self.life = random.randint(20, 45)
        self.max_life = self.life
        self.size = random.randint(2, 6)
        self.color = color

    def update(self):
        self.x  += self.vx
        self.y  += self.vy
        self.vy += 0.15   # gravity
        self.vx *= 0.96
        self.life -= 1

    def draw(self, frame):
        if self.life <= 0:
            return
        alpha = self.life / self.max_life
        size  = max(1, int(self.size * alpha))
        b, g, r = self.color
        c = (int(b * alpha), int(g * alpha), int(r * alpha))
        cv2.circle(frame, (int(self.x), int(self.y)), size, c, -1)

# ─────────────────────────────────────────────
#  SPACESHIP
# ─────────────────────────────────────────────
class Ship:
    def __init__(self):
        self.x      = WIN_W // 2
        self.y      = WIN_H - 80
        self.w      = 36
        self.h      = 44
        self.shield = False
        self.shield_hp = 0
        self.engine_flicker = 0

    def draw(self, frame, shield_active=False):
        cx, cy = int(self.x), int(self.y)

        # Engine glow
        self.engine_flicker = (self.engine_flicker + 1) % 8
        eg_size = 18 + (4 if self.engine_flicker < 4 else 0)
        draw_glow(frame, (cx, cy + self.h // 2 + 8), eg_size, (0, 120, 255), 0.4)
        cv2.ellipse(frame, (cx, cy + self.h // 2 + 8), (10, 7), 0, 0, 360,
                    (0, 80, 200), -1)

        # Ship body
        body = np.array([
            [cx,         cy - self.h // 2],
            [cx + self.w // 2, cy + self.h // 2],
            [cx - self.w // 2, cy + self.h // 2],
        ])
        cv2.fillPoly(frame, [body], C_SHIP)

        # Cockpit
        cv2.ellipse(frame, (cx, cy - 2), (10, 14), 0, 0, 360, (20, 180, 255), -1)
        cv2.ellipse(frame, (cx, cy - 2), (6, 9), 0, 0, 360, (180, 240, 255), -1)

        # Wings
        left_wing  = np.array([[cx - self.w//2, cy + self.h//2],
                                [cx - self.w,    cy + self.h//2 - 10],
                                [cx - self.w//4, cy]])
        right_wing = np.array([[cx + self.w//2, cy + self.h//2],
                                [cx + self.w,    cy + self.h//2 - 10],
                                [cx + self.w//4, cy]])
        cv2.fillPoly(frame, [left_wing],  C_SHIP_DARK)
        cv2.fillPoly(frame, [right_wing], C_SHIP_DARK)

        # Shield bubble
        if shield_active:
            draw_glow(frame, (cx, cy), 60, C_SHIELD, 0.25)
            cv2.ellipse(frame, (cx, cy), (55, 55), 0, 0, 360, C_SHIELD, 2)
            cv2.ellipse(frame, (cx, cy), (55, 55), 0, 0, 360,
                        (255, 255, 150), 1)

    def get_rect(self):
        return (self.x - self.w, self.y - self.h // 2, self.w * 2, self.h)

# ─────────────────────────────────────────────
#  HAND GESTURE DETECTOR
# ─────────────────────────────────────────────
class GestureDetector:
    def __init__(self):
        self.mp_hands = mp.solutions.hands
        self.hands    = self.mp_hands.Hands(
            static_image_mode=False,
            max_num_hands=1,
            min_detection_confidence=0.7,
            min_tracking_confidence=0.6)
        self.mp_draw  = mp.solutions.drawing_utils

        # State
        self.hand_x  = 0.5    # normalised 0–1
        self.hand_y  = 0.5
        self.gesture = 'none' # 'shoot', 'shield', 'fist', 'none'
        self.detected = False

    def count_fingers(self, lm):
        """Returns number of extended fingers (0–5)."""
        tips   = [4, 8, 12, 16, 20]
        bases  = [3, 6, 10, 14, 18]
        count  = 0
        # Thumb: compare x
        if lm[tips[0]].x < lm[bases[0]].x:
            count += 1
        # Other fingers
        for t, b in zip(tips[1:], bases[1:]):
            if lm[t].y < lm[b].y:
                count += 1
        return count

    def process(self, frame):
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        res = self.hands.process(rgb)
        self.detected = False
        self.gesture  = 'none'

        if res.multi_hand_landmarks:
            self.detected = True
            lm = res.multi_hand_landmarks[0].landmark

            # Position: use index finger MCP (knuckle) as reference
            self.hand_x = lm[9].x
            self.hand_y = lm[9].y

            fingers = self.count_fingers(lm)

            if   fingers == 0:
                self.gesture = 'fist'
            elif fingers == 1:
                self.gesture = 'shoot'
            elif fingers == 2:
                self.gesture = 'shield'
            else:
                self.gesture = 'none'

            # Draw landmarks on the small cam feed
            self.mp_draw.draw_landmarks(
                frame,
                res.multi_hand_landmarks[0],
                self.mp_hands.HAND_CONNECTIONS,
                self.mp_draw.DrawingSpec(color=(0,255,150), thickness=1, circle_radius=2),
                self.mp_draw.DrawingSpec(color=(0,180,255), thickness=1))

        return frame

# ─────────────────────────────────────────────
#  GAME MAIN
# ─────────────────────────────────────────────
class Game:
    def __init__(self):
        self.cap = cv2.VideoCapture(0)
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH,  640)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

        self.gd      = GestureDetector()
        self.ship    = Ship()
        self.bullets = []
        self.enemies = []
        self.particles = []
        self.stars   = [Star() for _ in range(STAR_COUNT)]

        self.score      = 0
        self.hi_score   = 0
        self.lives      = MAX_LIVES
        self.level      = 1
        self.kills      = 0
        self.kills_to_lvl = 10

        self.paused       = False
        self.game_over    = False
        self.show_splash  = True
        self.shield_active = False
        self.shield_used  = False

        self.last_shot_t    = 0
        self.last_enemy_t   = 0
        self.enemy_interval = 1.8

        self.prev_gesture   = 'none'
        self.fist_debounce  = 0

        self.frame_count = 0
        self.t_start     = time.time()

        # Target ship x from gesture
        self.target_x = WIN_W // 2

    # ── core reset ──────────────────────────
    def reset(self):
        self.ship       = Ship()
        self.bullets    = []
        self.enemies    = []
        self.particles  = []
        self.score      = 0
        self.lives      = MAX_LIVES
        self.level      = 1
        self.kills      = 0
        self.paused     = False
        self.game_over  = False
        self.shield_active = False
        self.shield_used   = False
        self.last_shot_t   = 0
        self.last_enemy_t  = 0
        self.enemy_interval = 1.8
        self.fist_debounce  = 0

    # ── spawn enemy ─────────────────────────
    def maybe_spawn_enemy(self):
        now = time.time()
        if now - self.last_enemy_t > self.enemy_interval:
            self.last_enemy_t   = now
            self.enemy_interval = max(0.4, 1.8 - self.level * 0.12)
            count = 1 + (self.level // 4)
            for _ in range(count):
                self.enemies.append(Enemy(self.level))

    # ── collision ───────────────────────────
    def check_collisions(self):
        def overlaps(r1, r2):
            x1,y1,w1,h1 = r1
            x2,y2,w2,h2 = r2
            return (x1 < x2+w2 and x1+w1 > x2 and
                    y1 < y2+h2 and y1+h1 > y2)

        sr = self.ship.get_rect()

        for e in self.enemies[:]:
            er = e.get_rect()
            # Bullet vs Enemy
            for b in self.bullets[:]:
                if b.active and overlaps(b.get_rect(), er):
                    b.active = False
                    destroyed = e.hit()
                    if destroyed:
                        self.score += e.points
                        self.kills += 1
                        self._explode(e.x, e.y, e.type)
                    break

            # Enemy vs Ship
            if e.active and overlaps(er, sr):
                e.active = False
                self._explode(e.x, e.y, e.type)
                if self.shield_active:
                    self.shield_active = False
                    self.shield_used   = True
                else:
                    self.lives -= 1
                    if self.lives <= 0:
                        self.game_over = True
                        self.hi_score  = max(self.hi_score, self.score)

        self.bullets = [b for b in self.bullets if b.active]
        self.enemies = [e for e in self.enemies if e.active]

    def _explode(self, x, y, etype):
        colors = {'A': C_ENEMY_A, 'B': C_ENEMY_B, 'C': C_DANGER}
        c = colors.get(etype, C_WHITE)
        for _ in range(25):
            self.particles.append(Particle(x, y, c))
        for _ in range(10):
            self.particles.append(Particle(x, y, C_WHITE))

    # ── level up ────────────────────────────
    def check_level(self):
        if self.kills >= self.kills_to_lvl:
            self.kills = 0
            self.kills_to_lvl = int(self.kills_to_lvl * 1.3)
            self.level += 1
            self.shield_used = False   # restore shield each level

    # ── HUD ─────────────────────────────────
    def draw_hud(self, frame):
        # Top bar bg
        cv2.rectangle(frame, (0, 0), (WIN_W, 50), (15, 10, 30), -1)
        cv2.line(frame, (0, 50), (WIN_W, 50), C_HUD_ACCENT, 1)

        font = cv2.FONT_HERSHEY_DUPLEX
        # Score
        cv2.putText(frame, f"SCORE  {self.score:06d}", (20, 34),
                    font, 0.65, C_HUD_ACCENT, 1, cv2.LINE_AA)
        # HI
        cv2.putText(frame, f"BEST  {self.hi_score:06d}",
                    (WIN_W // 2 - 80, 34), font, 0.65, C_YELLOW, 1, cv2.LINE_AA)
        # Level
        cv2.putText(frame, f"LVL {self.level}", (WIN_W - 120, 34),
                    font, 0.65, C_GREEN, 1, cv2.LINE_AA)

        # Lives (heart icons)
        for i in range(MAX_LIVES):
            cx = 30 + i * 30
            color = C_DANGER if i < self.lives else (50, 50, 80)
            cv2.circle(frame, (cx, WIN_H - 25), 9, color, -1)
            cv2.putText(frame, '♥', (cx - 8, WIN_H - 19),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255,255,255), 1)

        # Shield indicator
        sh_color = C_SHIELD if (not self.shield_used) else (60, 60, 80)
        cv2.putText(frame, "SHIELD", (WIN_W - 130, WIN_H - 18),
                    font, 0.5, sh_color, 1, cv2.LINE_AA)
        cv2.rectangle(frame, (WIN_W - 140, WIN_H - 35),
                      (WIN_W - 10, WIN_H - 8), sh_color, 1)

        # Gesture indicator
        g = self.gd.gesture
        g_icons = {'shoot': '☝  SHOOT', 'shield': '✌  SHIELD',
                   'fist': '✊  PAUSE', 'none': '✋  MOVE'}
        g_colors= {'shoot': C_BULLET, 'shield': C_SHIELD,
                   'fist': C_YELLOW, 'none': C_WHITE}
        txt  = g_icons.get(g, '— —')
        col  = g_colors.get(g, C_WHITE)
        cv2.putText(frame, txt, (WIN_W // 2 - 55, WIN_H - 18),
                    font, 0.55, col, 1, cv2.LINE_AA)

        # Kill progress bar
        bar_w = 160
        bar_x = WIN_W // 2 - bar_w // 2
        bar_y = WIN_H - 48
        cv2.rectangle(frame, (bar_x, bar_y), (bar_x + bar_w, bar_y + 6),
                      (40, 40, 60), -1)
        prog = int(bar_w * self.kills / self.kills_to_lvl)
        cv2.rectangle(frame, (bar_x, bar_y), (bar_x + prog, bar_y + 6),
                      C_HUD_ACCENT, -1)
        cv2.putText(frame, "NEXT LVL", (bar_x, bar_y - 3),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.35, C_HUD_ACCENT, 1)

    # ── PAUSE overlay ───────────────────────
    def draw_pause(self, frame):
        ov = frame.copy()
        cv2.rectangle(ov, (0, 0), (WIN_W, WIN_H), (5, 3, 15), -1)
        cv2.addWeighted(ov, 0.6, frame, 0.4, 0, frame)
        draw_text_centered(frame, "⏸  PAUSED", WIN_H // 2 - 30,
                           1.6, C_YELLOW, 2)
        draw_text_centered(frame, "Make a FIST to resume",
                           WIN_H // 2 + 30, 0.7, C_WHITE, 1)

    # ── GAME OVER overlay ───────────────────
    def draw_game_over(self, frame):
        ov = frame.copy()
        cv2.rectangle(ov, (0, 0), (WIN_W, WIN_H), (40, 0, 0), -1)
        cv2.addWeighted(ov, 0.55, frame, 0.45, 0, frame)
        draw_text_centered(frame, "GAME OVER",     WIN_H // 2 - 80, 2.2, C_DANGER, 3)
        draw_text_centered(frame, f"SCORE  {self.score:06d}", WIN_H // 2,    1.0, C_WHITE, 2)
        draw_text_centered(frame, f"BEST   {self.hi_score:06d}", WIN_H // 2 + 50, 1.0, C_YELLOW, 2)
        draw_text_centered(frame, "Show 1 finger to PLAY AGAIN",
                           WIN_H // 2 + 120, 0.65, C_HUD_ACCENT, 1)

    # ── SPLASH screen ───────────────────────
    def draw_splash(self, frame):
        # Animated bg
        t = time.time() * 0.5
        for i in range(5):
            r = int(200 + 50 * math.sin(t + i))
            cy = int(WIN_H // 2 + 120 * math.sin(t * 0.7 + i * 1.2))
            draw_glow(frame, (int(WIN_W * (i / 4)), cy), r,
                      [(0,50,150),(0,80,100),(20,30,100),(0,100,80),(10,60,120)][i], 0.12)

        draw_text_centered(frame, "GESTURE  SPACE  SHOOTER",
                           WIN_H // 2 - 100, 1.1, C_HUD_ACCENT, 2)
        draw_text_centered(frame, "Control your ship with your HAND",
                           WIN_H // 2 - 40, 0.65, C_WHITE, 1)

        instructions = [
            ("☝  1 Finger",  "SHOOT",  C_BULLET,  WIN_H // 2 + 20),
            ("✌  2 Fingers", "SHIELD", C_SHIELD,  WIN_H // 2 + 55),
            ("✊  Fist",      "PAUSE",  C_YELLOW,  WIN_H // 2 + 90),
            ("✋  Move",      "AIM",    C_GREEN,   WIN_H // 2 + 125),
        ]
        for icon, label, col, y in instructions:
            cv2.putText(frame, f"{icon}  →  {label}", (WIN_W // 2 - 140, y),
                        cv2.FONT_HERSHEY_DUPLEX, 0.6, col, 1, cv2.LINE_AA)

        draw_text_centered(frame, "Show 1 FINGER to start!",
                           WIN_H - 60, 0.75, C_HUD_ACCENT, 1)

    # ── Camera overlay ──────────────────────
    def draw_cam(self, frame, cam_small):
        cam_resized = cv2.resize(cam_small, (CAM_W, CAM_H))
        # Mirror for intuitive control
        cam_resized = cv2.flip(cam_resized, 1)
        # Border
        x, y = WIN_W - CAM_W - 10, WIN_H - CAM_H - 10
        # Semi-transparent bg
        ov = frame.copy()
        cv2.rectangle(ov, (x - 3, y - 3),
                      (x + CAM_W + 3, y + CAM_H + 3),
                      (20, 10, 40), -1)
        cv2.addWeighted(ov, 0.6, frame, 0.4, 0, frame)
        frame[y:y + CAM_H, x:x + CAM_W] = cam_resized
        cv2.rectangle(frame, (x - 2, y - 2),
                      (x + CAM_W + 2, y + CAM_H + 2),
                      C_HUD_ACCENT, 1)
        cv2.putText(frame, "CAMERA", (x + 4, y - 6),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, C_HUD_ACCENT, 1)

        # Crosshair tracking dot
        if self.gd.detected:
            tx = int(x + (1 - self.gd.hand_x) * CAM_W)
            ty = int(y + self.gd.hand_y * CAM_H)
            tx = max(x, min(x + CAM_W - 1, tx))
            ty = max(y, min(y + CAM_H - 1, ty))
            cv2.circle(frame, (tx, ty), 6, C_BULLET, 2)
            cv2.line(frame, (tx - 10, ty), (tx + 10, ty), C_BULLET, 1)
            cv2.line(frame, (tx, ty - 10), (tx, ty + 10), C_BULLET, 1)

    # ── MAIN LOOP ───────────────────────────
    def run(self):
        cv2.namedWindow("🚀 Gesture Space Shooter", cv2.WINDOW_NORMAL)
        cv2.resizeWindow("🚀 Gesture Space Shooter", WIN_W, WIN_H)

        clock_prev = time.time()

        while True:
            ret, cam_frame = self.cap.read()
            if not ret:
                print("[ERROR] Cannot read from camera.")
                break

            cam_frame = cv2.flip(cam_frame, 1)   # mirror
            cam_processed = self.gd.process(cam_frame.copy())

            # Build game canvas
            frame = np.full((WIN_H, WIN_W, 3), C_BG, dtype=np.uint8)

            # ── Stars ──
            for star in self.stars:
                star.update(self.level)
                star.draw(frame)

            # ── Splash ──────────────────────
            if self.show_splash:
                self.draw_splash(frame)
                self.draw_cam(frame, cam_processed)
                if self.gd.gesture == 'shoot':
                    self.show_splash = False
                cv2.imshow("🚀 Gesture Space Shooter", frame)
                if cv2.waitKey(1) & 0xFF == ord('q'):
                    break
                continue

            # ── Game Over ───────────────────
            if self.game_over:
                for e in self.enemies:
                    e.draw(frame)
                for p in self.particles:
                    p.update(); p.draw(frame)
                self.particles = [p for p in self.particles if p.life > 0]
                self.draw_game_over(frame)
                self.draw_cam(frame, cam_processed)
                if self.gd.gesture == 'shoot':
                    self.reset()
                cv2.imshow("🚀 Gesture Space Shooter", frame)
                if cv2.waitKey(1) & 0xFF == ord('q'):
                    break
                continue

            # ── Fist → toggle pause ──────────
            if self.gd.gesture == 'fist' and self.prev_gesture != 'fist':
                if self.fist_debounce <= 0:
                    self.paused = not self.paused
                    self.fist_debounce = 30

            if self.fist_debounce > 0:
                self.fist_debounce -= 1

            self.prev_gesture = self.gd.gesture

            if not self.paused:
                # ── Move ship ───────────────
                if self.gd.detected:
                    self.target_x = int((1 - self.gd.hand_x) * WIN_W)
                self.ship.x = lerp(self.ship.x, self.target_x, 0.18)
                self.ship.x = max(60, min(WIN_W - 60, self.ship.x))

                # ── Shield gesture ──────────
                self.shield_active = (self.gd.gesture == 'shield'
                                      and not self.shield_used)

                # ── Shooting ────────────────
                now = time.time()
                if (self.gd.gesture == 'shoot'
                        and now - self.last_shot_t > SHOOT_COOLDOWN):
                    self.last_shot_t = now
                    self.bullets.append(Bullet(self.ship.x, self.ship.y - 30))

                # ── Update bullets ──────────
                for b in self.bullets:
                    b.update()

                # ── Spawn enemies ───────────
                self.maybe_spawn_enemy()

                # ── Update enemies ──────────
                for e in self.enemies:
                    e.update()

                # ── Particles ───────────────
                for p in self.particles:
                    p.update()
                self.particles = [p for p in self.particles if p.life > 0]

                # ── Collisions ──────────────
                self.check_collisions()

                # ── Level up ────────────────
                self.check_level()

            # ── DRAW ────────────────────────
            for b in self.bullets:
                b.draw(frame)
            for e in self.enemies:
                e.draw(frame)
            for p in self.particles:
                p.draw(frame)
            self.ship.draw(frame, self.shield_active)

            self.draw_hud(frame)
            self.draw_cam(frame, cam_processed)

            if self.paused:
                self.draw_pause(frame)

            # ── FPS cap ─────────────────────
            self.frame_count += 1
            now = time.time()
            elapsed = now - clock_prev
            wait_ms = max(1, int((1 / FPS_CAP - elapsed) * 1000))
            clock_prev = time.time()

            cv2.imshow("🚀 Gesture Space Shooter", frame)
            key = cv2.waitKey(wait_ms) & 0xFF
            if key == ord('q') or key == 27:
                break
            if key == ord('r'):
                self.reset()

        self.cap.release()
        cv2.destroyAllWindows()


# ─────────────────────────────────────────────
#  ENTRY POINT
# ─────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 60)
    print("  🚀 GESTURE SPACE SHOOTER")
    print("=" * 60)
    print("  Controls:")
    print("    ☝  1 finger  → Shoot laser")
    print("    ✌  2 fingers → Activate shield")
    print("    ✊  Fist      → Pause / Resume")
    print("    ✋  Move hand → Steer spaceship")
    print()
    print("  Keys:")
    print("    Q / ESC      → Quit")
    print("    R            → Restart (keyboard shortcut)")
    print("=" * 60)
    print()

    try:
        game = Game()
        game.run()
    except ImportError as e:
        print(f"\n[MISSING DEPENDENCY] {e}")
        print("Run:  pip install opencv-python mediapipe numpy")
    except Exception as e:
        print(f"\n[ERROR] {e}")
        raise
