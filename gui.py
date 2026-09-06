
import os
import sys
import math
import time
import subprocess
from collections import deque
from pathlib import Path

import psutil
from PySide6.QtCore import Qt, QTimer, QPointF, QRectF, Signal, QObject, QProcess
from PySide6.QtGui import QColor, QPainter, QPen, QBrush, QFont, QLinearGradient, QRadialGradient, QAction
from PySide6.QtWidgets import (
    QApplication, QWidget, QMainWindow, QLabel, QVBoxLayout, QHBoxLayout,
    QFrame, QGraphicsDropShadowEffect, QSizePolicy, QMenu
)

APP_TITLE = "ULTRON // SYSTEM INTERFACE"

BG = QColor("#050506")
PANEL = QColor("#0b0b0d")
PANEL_ALT = QColor("#101014")
RED = QColor("#ff1f2f")
RED_SOFT = QColor("#a70e1b")
RED_DARK = QColor("#3a050a")
WHITE = QColor("#f2f2f2")
MUTED = QColor("#7d7d84")
GRID = QColor("#211014")

class CoreWidget(QWidget):
    def __init__(self):
        super().__init__()
        self.setMinimumSize(560, 560)
        self.phase = 0.0
        self.state = "STANDBY"
        self.activity = 0.15
        self.target_activity = 0.15
        self.speaking = False
        self.speech_phase = 0.0
        self.speech_energy = 0.0
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(16)

    def set_state(self, state):
        state = state.upper()
        self.state = state
        mapping = {
            "STANDBY": 0.15,
            "ACTIVE": 0.38,
            "LISTENING": 0.62,
            "THINKING": 0.84,
            "EXECUTING": 1.0,
            "VISION": 0.9,
            "AGENT": 1.0,
            "TEACH": 0.96,
            "COMPLETE": 0.76,
            "ERROR": 1.0,
            "SPEAKING": 0.9,
        }
        self.target_activity = mapping.get(state, 0.4)

    def set_speaking(self, speaking):
        self.speaking = bool(speaking)
        if speaking:
            self.state = "SPEAKING"
            self.target_activity = 0.95
        else:
            self.state = "ACTIVE"
            self.target_activity = 0.42

    def tick(self):
        self.phase += 0.018 + self.activity * 0.025
        self.speech_phase += 0.19
        self.activity += (self.target_activity - self.activity) * 0.08
        target_speech = 1.0 if self.speaking else 0.0
        self.speech_energy += (target_speech - self.speech_energy) * 0.18
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        c = QPointF(w/2, h/2)
        min_dim = min(w, h)

        # More obvious "breathing" while TTS is active:
        # combine slow and fast waves so it feels speech-like rather than mechanical.
        voice_wave = (
            math.sin(self.speech_phase) * 0.055 +
            math.sin(self.speech_phase * 2.37 + 0.7) * 0.028 +
            math.sin(self.speech_phase * 0.53 + 1.8) * 0.018
        ) * self.speech_energy
        idle_wave = math.sin(self.phase * 2.1) * 0.018 * (0.3 + self.activity)
        scale = 1.0 + idle_wave + voice_wave

        core_r = min_dim * 0.118 * scale
        orbit_scale = 1.0 + voice_wave * 0.7

        # Ambient red bloom behind the whole reactor.
        ambient = QRadialGradient(c, min_dim * 0.48)
        ambient.setColorAt(0.0, QColor(100, 0, 10, int(42 + 35*self.activity)))
        ambient.setColorAt(0.45, QColor(75, 0, 8, int(20 + 20*self.activity)))
        ambient.setColorAt(1.0, QColor(0, 0, 0, 0))
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(ambient))
        p.drawEllipse(c, min_dim*0.48, min_dim*0.48)

        # HUD corner brackets to make the centre feel occupied.
        bracket_pen = QPen(QColor(255, 32, 48, 105), 1.4)
        p.setPen(bracket_pen)
        pad = min_dim * 0.09
        arm = min_dim * 0.06
        # top-left
        p.drawLine(QPointF(pad,pad), QPointF(pad+arm,pad))
        p.drawLine(QPointF(pad,pad), QPointF(pad,pad+arm))
        # top-right
        p.drawLine(QPointF(w-pad,pad), QPointF(w-pad-arm,pad))
        p.drawLine(QPointF(w-pad,pad), QPointF(w-pad,pad+arm))
        # bottom-left
        p.drawLine(QPointF(pad,h-pad), QPointF(pad+arm,h-pad))
        p.drawLine(QPointF(pad,h-pad), QPointF(pad,h-pad-arm))
        # bottom-right
        p.drawLine(QPointF(w-pad,h-pad), QPointF(w-pad-arm,h-pad))
        p.drawLine(QPointF(w-pad,h-pad), QPointF(w-pad,h-pad-arm))

        # crosshair + concentric scanning circles
        p.setPen(QPen(QColor(90, 18, 24, 120), 1))
        p.drawLine(0, int(c.y()), w, int(c.y()))
        p.drawLine(int(c.x()), 0, int(c.x()), h)
        for rr in [0.20, 0.255, 0.31, 0.385, 0.455]:
            r=min_dim*rr
            alpha=55 if rr < 0.35 else 28
            p.setPen(QPen(QColor(110,18,25,alpha),1))
            p.drawEllipse(c, r, r)

        # rotating sweep arc / radar scanner
        sweep_r=min_dim*0.345
        p.save()
        p.translate(c)
        p.rotate((self.phase*38) % 360)
        p.setPen(QPen(QColor(255,35,50,95), 2.2))
        p.drawArc(QRectF(-sweep_r,-sweep_r,sweep_r*2,sweep_r*2), 0, 58*16)
        p.restore()

        # outer ticks
        tick_r = min_dim * 0.402 * orbit_scale
        p.save()
        p.translate(c)
        p.rotate(self.phase*18)
        for i in range(96):
            a = math.radians(i*3.75)
            major = i % 8 == 0
            length = 14 if major else 5
            alpha = 145 if major else 42
            p.setPen(QPen(QColor(255,31,47,alpha), 1.3 if major else 0.8))
            x1=math.cos(a)*tick_r
            y1=math.sin(a)*tick_r
            x2=math.cos(a)*(tick_r+length)
            y2=math.sin(a)*(tick_r+length)
            p.drawLine(QPointF(x1,y1),QPointF(x2,y2))
        p.restore()

        # orbit ellipses: stronger and slightly voice-reactive
        orbit_specs = [
            (0.305, 0.122, self.phase*29),
            (0.325, 0.095, -self.phase*35 + 50),
            (0.272, 0.155, self.phase*24 + 110),
            (0.355, 0.074, -self.phase*18 + 20),
        ]
        for index,(rx_f, ry_f, angle) in enumerate(orbit_specs):
            p.save()
            p.translate(c)
            p.rotate(angle)
            alpha=int(115 + 90*self.activity)
            width=2.2 if index < 3 else 1.2
            p.setPen(QPen(QColor(255,45,58,alpha), width))
            p.setBrush(Qt.NoBrush)
            rect=QRectF(
                -min_dim*rx_f*orbit_scale, -min_dim*ry_f*orbit_scale,
                min_dim*rx_f*2*orbit_scale, min_dim*ry_f*2*orbit_scale
            )
            p.drawEllipse(rect)

            # orbiting node
            if index < 3:
                node_x=min_dim*rx_f*orbit_scale
                node_y=0
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(255,85,95,210))
                p.drawEllipse(QPointF(node_x,node_y), 4.2, 4.2)
            p.restore()

        # voice equalizer halo: appears only while Ultron talks
        if self.speech_energy > 0.02:
            bar_base=min_dim*0.47
            p.save()
            p.translate(c)
            for i in range(48):
                a=math.radians(i*7.5)
                wave = (
                    0.45 +
                    0.30*math.sin(self.speech_phase*1.35+i*0.57) +
                    0.18*math.sin(self.speech_phase*2.2+i*0.19)
                )
                level=max(0.08,min(1.0,wave))*self.speech_energy
                l=5 + 22*level
                x1=math.cos(a)*bar_base
                y1=math.sin(a)*bar_base
                x2=math.cos(a)*(bar_base+l)
                y2=math.sin(a)*(bar_base+l)
                p.setPen(QPen(QColor(255,55,70,int(80+160*level)),1.5))
                p.drawLine(QPointF(x1,y1),QPointF(x2,y2))
            p.restore()

        # glow rings
        for k in range(9, 0, -1):
            alpha=int((8+k*5)*(0.38+self.activity))
            p.setPen(QPen(QColor(255,25,40,alpha), k*2.2))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(c, core_r+k*4, core_r+k*4)

        # core radial gradient
        grad=QRadialGradient(c, core_r*1.48)
        grad.setColorAt(0.0, QColor(255,255,255,255))
        grad.setColorAt(0.13, QColor(255,220,222,252))
        grad.setColorAt(0.35, QColor(255,95,105,250))
        grad.setColorAt(0.62, QColor(255,30,46,245))
        grad.setColorAt(1.0, QColor(120,0,8,15))
        p.setBrush(QBrush(grad))
        p.setPen(Qt.NoPen)
        p.drawEllipse(c, core_r*1.34, core_r*1.34)

        # bright hot inner center
        inner=QRadialGradient(c, core_r*0.58)
        inner.setColorAt(0,QColor(255,255,255,255))
        inner.setColorAt(0.55,QColor(255,180,185,180))
        inner.setColorAt(1,QColor(255,50,65,0))
        p.setBrush(QBrush(inner))
        p.drawEllipse(c,core_r*0.62,core_r*0.62)

        # central plate
        plate_w=242 + 18*self.speech_energy
        plate_h=54
        p.setBrush(QBrush(QColor(8,4,6,200)))
        p.setPen(QPen(QColor(255,65,78,210),1.2))
        plate=QRectF(c.x()-plate_w/2,c.y()-plate_h/2,plate_w,plate_h)
        p.drawRoundedRect(plate,6,6)
        p.setPen(WHITE)
        f=QFont("Segoe UI", 20, QFont.DemiBold)
        f.setLetterSpacing(QFont.AbsoluteSpacing, 7)
        p.setFont(f)
        p.drawText(plate, Qt.AlignCenter, "ULTRON")

        # status
        status_rect=QRectF(c.x()-170,c.y()+50,340,36)
        p.setPen(QColor(255,115,125,230))
        sf=QFont("Consolas", 10, QFont.Bold)
        sf.setLetterSpacing(QFont.AbsoluteSpacing,2)
        p.setFont(sf)
        p.drawText(status_rect, Qt.AlignCenter, self.state)

        # Peripheral HUD labels
        small=QFont("Consolas",8,QFont.Bold)
        small.setLetterSpacing(QFont.AbsoluteSpacing,1.4)
        p.setFont(small)
        hud_alpha=int(105+80*self.activity)
        p.setPen(QColor(255,80,90,hud_alpha))
        labels = [
            (QRectF(30, h*0.28, 150, 22), "CORE LINK // STABLE", Qt.AlignLeft),
            (QRectF(w-180, h*0.28, 150, 22), "NEURAL BUS // LIVE", Qt.AlignRight),
            (QRectF(30, h*0.70, 150, 22), "VOICE CHANNEL // 01", Qt.AlignLeft),
            (QRectF(w-180, h*0.70, 150, 22), "AUTONOMY // ARMED", Qt.AlignRight),
        ]
        for rect,text,align in labels:
            p.drawText(rect,align|Qt.AlignVCenter,text)

        # more particles / sparks
        p.setPen(Qt.NoPen)
        for i in range(34):
            a=self.phase*(0.55+i*0.018)+i*0.71
            rr=min_dim*(0.17 + (i%8)*0.037)
            x=c.x()+math.cos(a)*rr
            y=c.y()+math.sin(a*1.13)*rr*0.66
            size=1.0+(i%4)*0.65
            alpha=55+(i%5)*16
            p.setBrush(QColor(255,45,60,alpha))
            p.drawEllipse(QPointF(x,y),size,size)


class FloatingUltron(QWidget):
    restoreRequested = Signal()
    exitRequested = Signal()

    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            Qt.FramelessWindowHint |
            Qt.Tool |
            Qt.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setFixedSize(190, 190)
        self.phase = 0.0
        self.state = "ACTIVE"
        self.speaking = False
        self.speech_energy = 0.0
        self._drag_offset = None
        self._dragged = False

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(16)

    def tick(self):
        self.phase += 0.055
        target = 1.0 if self.speaking else 0.0
        self.speech_energy += (target-self.speech_energy)*0.2
        self.update()

    def set_state(self, state):
        self.state = str(state or "ACTIVE").upper()
        self.update()

    def set_speaking(self, speaking):
        self.speaking = bool(speaking)
        if speaking:
            self.state = "SPEAKING"
        self.update()

    def move_to_default_corner(self):
        screen = QApplication.primaryScreen()
        if not screen:
            return
        geo = screen.availableGeometry()
        margin = 24
        self.move(
            geo.right() - self.width() - margin,
            geo.bottom() - self.height() - margin
        )

    def show_companion(self):
        if not self.isVisible():
            self.move_to_default_corner()
        self.show()
        self.raise_()
        self.activateWindow()

    def paintEvent(self, event):
        p=QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w,h=self.width(),self.height()
        c=QPointF(w/2,h/2-6)

        # Glassy circular background, mostly transparent.
        bg=QRadialGradient(c,82)
        bg.setColorAt(0,QColor(32,3,8,205))
        bg.setColorAt(0.72,QColor(10,5,8,180))
        bg.setColorAt(1,QColor(0,0,0,0))
        p.setPen(Qt.NoPen)
        p.setBrush(bg)
        p.drawEllipse(c,82,82)

        # animated voice pulse
        voice_wave=(
            math.sin(self.phase*2.9)*0.10 +
            math.sin(self.phase*6.1+0.7)*0.045
        )*self.speech_energy
        base=33
        r=base*(1+voice_wave)

        # outer orbit rings
        for idx,(rx,ry,speed) in enumerate([
            (61,22,1.0),(58,28,-1.25),(50,34,0.72)
        ]):
            p.save()
            p.translate(c)
            p.rotate(self.phase*32*speed + idx*55)
            p.setPen(QPen(QColor(255,45,62,160 if idx<2 else 95),1.8 if idx<2 else 1.1))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(QRectF(-rx,-ry,rx*2,ry*2))
            if idx<2:
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(255,100,110,230))
                p.drawEllipse(QPointF(rx,0),3.4,3.4)
            p.restore()

        # speaking equalizer ticks
        if self.speech_energy > 0.03:
            p.save()
            p.translate(c)
            for i in range(28):
                a=math.radians(i*(360/28))
                amp=(0.45+0.35*math.sin(self.phase*5.0+i*.7))*self.speech_energy
                l=4+10*max(.05,amp)
                rr=70
                p.setPen(QPen(QColor(255,65,80,int(80+150*amp)),1.3))
                p.drawLine(
                    QPointF(math.cos(a)*rr,math.sin(a)*rr),
                    QPointF(math.cos(a)*(rr+l),math.sin(a)*(rr+l))
                )
            p.restore()

        # glow
        for k in range(7,0,-1):
            p.setPen(QPen(QColor(255,25,45,18+k*8),k*1.8))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(c,r+k*2.5,r+k*2.5)

        grad=QRadialGradient(c,r*1.4)
        grad.setColorAt(0,QColor(255,255,255,255))
        grad.setColorAt(.20,QColor(255,190,195,250))
        grad.setColorAt(.52,QColor(255,55,70,245))
        grad.setColorAt(1,QColor(110,0,10,20))
        p.setBrush(grad)
        p.setPen(Qt.NoPen)
        p.drawEllipse(c,r*1.25,r*1.25)

        # central U
        p.setPen(QColor(255,255,255,235))
        f=QFont("Segoe UI",18,QFont.Bold)
        p.setFont(f)
        p.drawText(QRectF(c.x()-26,c.y()-22,52,44),Qt.AlignCenter,"U")

        # status capsule
        capsule=QRectF(31,145,128,25)
        p.setBrush(QColor(7,5,7,220))
        p.setPen(QPen(QColor(255,50,66,160),1))
        p.drawRoundedRect(capsule,8,8)
        p.setPen(QColor(255,110,120,230))
        sf=QFont("Consolas",8,QFont.Bold)
        sf.setLetterSpacing(QFont.AbsoluteSpacing,1)
        p.setFont(sf)
        display=self.state[:14]
        p.drawText(capsule,Qt.AlignCenter,display)

        # tiny status dot
        p.setPen(Qt.NoPen)
        dot=QColor("#ff3140")
        if self.state=="STANDBY":
            dot=QColor("#7d2028")
        elif self.state=="ERROR":
            dot=QColor("#ff0019")
        p.setBrush(dot)
        p.drawEllipse(QPointF(169,20),4,4)

    def mousePressEvent(self,event):
        if event.button()==Qt.LeftButton:
            self._drag_offset=event.globalPosition().toPoint()-self.frameGeometry().topLeft()
            self._dragged=False
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self,event):
        if self._drag_offset is not None and (event.buttons() & Qt.LeftButton):
            self._dragged=True
            self.move(event.globalPosition().toPoint()-self._drag_offset)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self,event):
        if event.button()==Qt.LeftButton:
            if self._drag_offset is not None and not self._dragged:
                self.restoreRequested.emit()
            self._drag_offset=None
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def contextMenuEvent(self,event):
        menu=QMenu(self)
        menu.setStyleSheet("""
            QMenu { background:#0b080a; color:white; border:1px solid #5a1019; padding:5px; }
            QMenu::item { padding:7px 22px; }
            QMenu::item:selected { background:#3c0a11; }
        """)
        restore=QAction("Open Ultron",self)
        exit_action=QAction("Exit Ultron",self)
        restore.triggered.connect(self.restoreRequested.emit)
        exit_action.triggered.connect(self.exitRequested.emit)
        menu.addAction(restore)
        menu.addSeparator()
        menu.addAction(exit_action)
        menu.exec(event.globalPos())

class Section(QFrame):
    def __init__(self, title):
        super().__init__()
        self.setObjectName("section")
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(16, 14, 16, 14)
        self.layout.setSpacing(8)
        lab=QLabel(title.upper())
        lab.setObjectName("sectionTitle")
        self.layout.addWidget(lab)

class MetricRow(QWidget):
    def __init__(self, name, value="--"):
        super().__init__()
        lay=QHBoxLayout(self)
        lay.setContentsMargins(0,0,0,0)
        self.name=QLabel(name)
        self.name.setObjectName("metricName")
        self.value=QLabel(value)
        self.value.setObjectName("metricValue")
        self.value.setAlignment(Qt.AlignRight)
        lay.addWidget(self.name)
        lay.addStretch()
        lay.addWidget(self.value)

    def set_value(self, value):
        self.value.setText(str(value))

class ModuleRow(QWidget):
    def __init__(self, name):
        super().__init__()
        lay=QHBoxLayout(self)
        lay.setContentsMargins(0,0,0,0)
        self.dot=QLabel("●")
        self.dot.setObjectName("moduleDot")
        self.label=QLabel(name.upper())
        self.label.setObjectName("moduleName")
        self.state=QLabel("READY")
        self.state.setObjectName("moduleState")
        self.state.setAlignment(Qt.AlignRight)
        lay.addWidget(self.dot)
        lay.addWidget(self.label)
        lay.addStretch()
        lay.addWidget(self.state)
        self.active=False

    def set_active(self, active=True, text=None):
        self.active=active
        self.dot.setStyleSheet(f"color: {'#ff2534' if active else '#4b2025'};")
        self.label.setStyleSheet(f"color: {'#ffffff' if active else '#8c8c91'};")
        self.state.setText(text or ("ACTIVE" if active else "READY"))

class TimelineRow(QWidget):
    def __init__(self, label, status=""):
        super().__init__()
        lay=QHBoxLayout(self)
        lay.setContentsMargins(0,0,0,0)
        a=QLabel(label)
        a.setObjectName("timelineText")
        b=QLabel(status)
        b.setObjectName("timelineStatus")
        b.setAlignment(Qt.AlignRight)
        lay.addWidget(a)
        lay.addStretch()
        lay.addWidget(b)

class UltronWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_TITLE)
        self.setMinimumSize(1280, 760)
        self.setWindowFlag(Qt.FramelessWindowHint, True)
        self.setStyleSheet(self.stylesheet())

        self.process = QProcess(self)
        self.process.setProcessChannelMode(QProcess.MergedChannels)
        self.process.readyReadStandardOutput.connect(self.read_backend)
        self.process.finished.connect(self.backend_finished)

        self.current_state="STANDBY"
        self.timeline=deque(maxlen=6)
        self.modules={}
        self.compact_mode=False
        self._last_core_state="STANDBY"
        self.floating=FloatingUltron()
        self.floating.restoreRequested.connect(self.restore_dashboard)
        self.floating.exitRequested.connect(self.close)
        self.build_ui()
        self.start_backend()

        self.stats_timer=QTimer(self)
        self.stats_timer.timeout.connect(self.refresh_stats)
        self.stats_timer.start(1200)
        self.refresh_stats()

    def collapse_to_companion(self, reason="working"):
        if self.compact_mode:
            return
        self.compact_mode=True
        self.floating.set_state(self._last_core_state or "EXECUTING")
        self.floating.show_companion()
        self.hide()
        print(f"GUI> FLOATING COMPANION | {reason}")

    def restore_dashboard(self):
        self.compact_mode=False
        self.floating.hide()
        self.showMaximized()
        self.raise_()
        self.activateWindow()
        print("GUI> FULL DASHBOARD")

    def sync_visual_state(self, state):
        self._last_core_state=str(state or "ACTIVE").upper()
        self.core.set_state(self._last_core_state)
        self.floating.set_state(self._last_core_state)

    def set_visual_speaking(self, speaking):
        self.core.set_speaking(speaking)
        self.floating.set_speaking(speaking)
        if not speaking:
            # Return both reactors to the task state they had before speech.
            self.core.set_state(self._last_core_state)
            self.floating.set_state(self._last_core_state)

    def stylesheet(self):
        return """
        QMainWindow, QWidget { background:#050506; color:#f2f2f2; font-family:'Segoe UI'; }
        #topBar { background:#0b080a; border-bottom:2px solid #5a1019; }
        #brand { font-size:16px; font-weight:700; letter-spacing:4px; color:#ffffff; }
        #live { font-family:Consolas; color:#ff3140; font-size:11px; }
        #section { background:#0d090b; border:1px solid #491018; border-radius:8px; }
        #sectionTitle { color:#ff4453; font-size:10px; font-weight:800; letter-spacing:3px; padding-bottom:4px; }
        #metricName { color:#7f7f86; font-family:Consolas; font-size:11px; }
        #metricValue { color:#efefef; font-family:Consolas; font-size:11px; font-weight:700; }
        #moduleName { color:#8c8c91; font-family:Consolas; font-size:11px; font-weight:700; letter-spacing:1px; }
        #moduleDot { color:#4b2025; font-size:12px; }
        #moduleState { color:#5f5f64; font-family:Consolas; font-size:9px; }
        #heardLabel { color:#68686d; font-family:Consolas; font-size:10px; letter-spacing:2px; }
        #heardText { color:#ffffff; font-size:20px; font-weight:700; }
        #subStatus { color:#ff3544; font-family:Consolas; font-size:11px; letter-spacing:2px; }
        #timelineText { color:#a7a7ac; font-family:Consolas; font-size:10px; }
        #timelineStatus { color:#ff3544; font-family:Consolas; font-size:10px; font-weight:700; }
        #footer { background:#08080a; border-top:1px solid #301015; }
        #footerText { color:#727279; font-family:Consolas; font-size:10px; letter-spacing:1px; }
        """

    def build_ui(self):
        root=QWidget()
        self.setCentralWidget(root)
        main=QVBoxLayout(root)
        main.setContentsMargins(0,0,0,0)
        main.setSpacing(0)

        top=QFrame()
        top.setObjectName("topBar")
        top.setFixedHeight(58)
        tl=QHBoxLayout(top)
        tl.setContentsMargins(24,0,24,0)
        brand=QLabel("ULTRON // SYSTEM INTERFACE")
        brand.setObjectName("brand")
        self.live=QLabel("● CORE ONLINE")
        self.live.setObjectName("live")
        self.clock=QLabel("--:--:--")
        self.clock.setObjectName("live")
        tl.addWidget(brand)
        tl.addStretch()
        tl.addWidget(self.live)
        tl.addSpacing(20)
        tl.addWidget(self.clock)
        main.addWidget(top)

        body=QHBoxLayout()
        body.setContentsMargins(18,16,18,16)
        body.setSpacing(16)

        # left
        left=QVBoxLayout()
        left.setSpacing(12)
        sys_sec=Section("System")
        self.cpu=MetricRow("CPU","--")
        self.ram=MetricRow("MEMORY","--")
        self.battery=MetricRow("BATTERY","--")
        self.net=MetricRow("NETWORK","ONLINE")
        self.mic=MetricRow("MIC","ARMED")
        self.disk=MetricRow("DISK","--")
        self.proc=MetricRow("PROCESSES","--")
        self.uptime=MetricRow("UPTIME","--")
        for x in [self.cpu,self.ram,self.battery,self.disk,self.proc,self.uptime,self.net,self.mic]:
            sys_sec.layout.addWidget(x)
        left.addWidget(sys_sec)

        task_sec=Section("Current task")
        self.task_status=QLabel("WAITING FOR WAKE WORD")
        self.task_status.setObjectName("subStatus")
        self.task_text=QLabel("No active task")
        self.task_text.setObjectName("metricValue")
        self.task_text.setWordWrap(True)
        task_sec.layout.addWidget(self.task_status)
        task_sec.layout.addWidget(self.task_text)
        left.addWidget(task_sec)

        diag=Section("Diagnostics")
        self.route=MetricRow("ROUTE","—")
        self.mode=MetricRow("MODE","STANDBY")
        self.mem=MetricRow("MEMORIES","—")
        diag.layout.addWidget(self.route)
        diag.layout.addWidget(self.mode)
        diag.layout.addWidget(self.mem)
        left.addWidget(diag)
        left.addStretch()

        # center
        center=QVBoxLayout()
        center.setSpacing(0)
        self.core=CoreWidget()
        center.addWidget(self.core,1)

        heard_box=QFrame()
        heard_box.setObjectName("section")
        hl=QVBoxLayout(heard_box)
        hl.setContentsMargins(20,14,20,14)
        head=QLabel("VOICE INPUT")
        head.setObjectName("heardLabel")
        self.heard=QLabel("Say “Ultron” to activate")
        self.heard.setObjectName("heardText")
        self.heard.setWordWrap(True)
        hl.addWidget(head)
        hl.addWidget(self.heard)
        center.addWidget(heard_box)

        signal_box=QFrame()
        signal_box.setObjectName("section")
        sl=QHBoxLayout(signal_box)
        sl.setContentsMargins(18,8,18,8)
        self.signal_left=QLabel("SIGNAL  ▮▮▮▮▮▯▯▯")
        self.signal_left.setObjectName("subStatus")
        self.signal_mid=QLabel("ENCRYPTED CHANNEL")
        self.signal_mid.setObjectName("footerText")
        self.signal_right=QLabel("LATENCY  LOCAL")
        self.signal_right.setObjectName("subStatus")
        sl.addWidget(self.signal_left)
        sl.addStretch()
        sl.addWidget(self.signal_mid)
        sl.addStretch()
        sl.addWidget(self.signal_right)
        center.addWidget(signal_box)

        # right
        right=QVBoxLayout()
        right.setSpacing(12)
        modules=Section("Modules")
        for name in ["VOICE","VISION","MEMORY","PLANNER","AGENT","TEACH","DESKTOP"]:
            row=ModuleRow(name)
            self.modules[name]=row
            modules.layout.addWidget(row)
        right.addWidget(modules)

        timeline_sec=Section("Execution timeline")
        self.timeline_layout=timeline_sec.layout
        self.timeline_rows=[]
        for _ in range(6):
            row=TimelineRow("—","")
            self.timeline_rows.append(row)
            self.timeline_layout.addWidget(row)
        right.addWidget(timeline_sec,1)

        body.addLayout(left, 22)
        body.addLayout(center, 56)
        body.addLayout(right, 22)
        main.addLayout(body,1)

        footer=QFrame()
        footer.setObjectName("footer")
        footer.setFixedHeight(34)
        fl=QHBoxLayout(footer)
        fl.setContentsMargins(20,0,20,0)
        self.footer_text=QLabel("F11 FULLSCREEN   •   ESC WINDOWED   •   UI: v11.3 FLOATING COMPANION   •   BACKEND: v11.0")
        self.footer_text.setObjectName("footerText")
        fl.addWidget(self.footer_text)
        fl.addStretch()
        self.backend_state=QLabel("BACKEND STARTING")
        self.backend_state.setObjectName("footerText")
        fl.addWidget(self.backend_state)
        main.addWidget(footer)

    def start_backend(self):
        script=os.path.join(os.path.dirname(__file__),"main.py")
        self.process.setWorkingDirectory(os.path.dirname(script))
        self.process.start(sys.executable, ["-u", script])
        self.backend_state.setText("BACKEND STARTING")

    def backend_finished(self, code, status):
        self.backend_state.setText(f"BACKEND OFFLINE ({code})")
        self.sync_visual_state("ERROR")

    def add_timeline(self, text, status=""):
        self.timeline.appendleft((text[:44],status))
        for i,row in enumerate(self.timeline_rows):
            lay=row.layout()
            labels=[lay.itemAt(j).widget() for j in range(lay.count()) if lay.itemAt(j).widget()]
            if i < len(self.timeline):
                text,status=self.timeline[i]
                labels[0].setText(text)
                labels[-1].setText(status)
            else:
                labels[0].setText("—")
                labels[-1].setText("")

    def set_all_modules(self, active=False):
        for row in self.modules.values():
            row.set_active(active)

    def pulse_module(self, name, text="ACTIVE"):
        if name in self.modules:
            self.modules[name].set_active(True,text)

    def read_backend(self):
        raw=bytes(self.process.readAllStandardOutput()).decode(errors="ignore")
        for line in raw.splitlines():
            line=line.strip()
            if not line:
                continue
            print(line)
            self.parse_line(line)

    def parse_line(self,line):
        self.backend_state.setText("BACKEND ONLINE")
        upper=line.upper()

        if line.startswith("TTS START>"):
            self.set_visual_speaking(True)
            self.task_status.setText("ULTRON SPEAKING")
            self.modules["VOICE"].set_active(True,"OUTPUT")
            self.add_timeline("VOICE OUTPUT","SPEAKING")
            return

        if line.startswith("TTS END>"):
            self.set_visual_speaking(False)
            self.task_status.setText("READY")
            self.modules["VOICE"].set_active(True,"ACTIVE")
            self.add_timeline("VOICE OUTPUT","DONE")
            return

        if line.startswith("STATE>"):
            state=line.split(">",1)[1].strip().upper()
            self.mode.set_value(state)
            if state=="STANDBY":
                self.sync_visual_state("STANDBY")
                self.heard.setText("Say “Ultron” to activate")
                self.task_status.setText("STANDBY")
                self.set_all_modules(False)
                self.modules["VOICE"].set_active(True,"ARMED")
            elif state=="ACTIVE":
                self.sync_visual_state("ACTIVE")
                self.task_status.setText("ACTIVE SESSION")
                self.modules["VOICE"].set_active(True,"ACTIVE")
            return

        if line.startswith("MIC> Listening"):
            if self.mode.value.text()=="ACTIVE":
                self.sync_visual_state("LISTENING")
            self.modules["VOICE"].set_active(True,"LISTENING")
            return

        if line.startswith("YOU>"):
            text=line.split(">",1)[1].strip()
            self.heard.setText(text)
            self.task_text.setText(text)
            self.task_status.setText("UNDERSTANDING")
            self.sync_visual_state("THINKING")
            self.add_timeline("VOICE INPUT","RECEIVED")
            return

        if line.startswith("ROUTE>"):
            route=line.split(">",1)[1].strip()
            intent=route.split("|")[0].strip().lower()
            self.route.set_value(intent)
            self.add_timeline(route,"ROUTED")

            # When another app/browser is about to take focus, collapse the large
            # dashboard but keep Ultron visible as an always-on-top companion.
            foreground_intents = {
                "open_app", "open_website", "open_setting", "open_folder",
                "open_file", "smart_file_open", "open_in_vscode",
                "search_google", "search_youtube", "search_site",
                "play_youtube", "play_spotify", "spotify_search",
                "open_first_site_result"
            }
            if intent in foreground_intents:
                self.sync_visual_state("EXECUTING")
                QTimer.singleShot(180, lambda i=intent: self.collapse_to_companion(i))
            if "vision" in route.lower() or "screen" in route.lower():
                self.sync_visual_state("VISION")
                self.pulse_module("VISION")
            elif "memory" in route.lower() or "remember" in route.lower():
                self.pulse_module("MEMORY")
            else:
                self.pulse_module("DESKTOP")
            return

        if line.startswith("PLAN>") or line.startswith("PLAN STEP>"):
            self.sync_visual_state("EXECUTING")
            self.pulse_module("PLANNER")
            self.add_timeline(line.replace(">","",1),"RUNNING")
            low=line.lower()
            if line.startswith("PLAN STEP>") and any(x in low for x in [
                "open_app", "open_website", "open_setting", "open_folder",
                "search_google", "search_youtube", "search_site", "play_youtube",
                "play_spotify", "open_file"
            ]):
                QTimer.singleShot(150, lambda: self.collapse_to_companion("planner"))
            return

        if line.startswith("PLAN RESULT>"):
            ok="success=True" in line
            self.add_timeline("PLAN STEP", "✓ DONE" if ok else "FAILED")
            self.sync_visual_state("COMPLETE" if ok else "ERROR")
            return

        if line.startswith("AGENT"):
            self.sync_visual_state("AGENT")
            if not self.compact_mode:
                QTimer.singleShot(120, lambda: self.collapse_to_companion("agent"))
            self.pulse_module("AGENT")
            self.pulse_module("VISION")
            self.add_timeline(line.split(">",1)[0],"ACTIVE")
            return

        if line.startswith("TEACH>"):
            self.sync_visual_state("TEACH")
            self.pulse_module("TEACH","LEARNING")
            self.add_timeline("TEACH MODE",line.split(">",1)[1].strip()[:25])
            return

        if line.startswith("TEACH EVENT>"):
            self.sync_visual_state("TEACH")
            self.pulse_module("TEACH","RECORDING")
            self.add_timeline(line.split(">",1)[1].strip(),"OBSERVED")
            return

        if line.startswith("TEACH REPLAY"):
            self.sync_visual_state("EXECUTING")
            if not self.compact_mode:
                QTimer.singleShot(120, lambda: self.collapse_to_companion("workflow replay"))
            self.pulse_module("TEACH","REPLAY")
            self.add_timeline("LEARNED WORKFLOW","REPLAY")
            return

        if line.startswith("VISION"):
            self.sync_visual_state("VISION")
            self.pulse_module("VISION","SCANNING")
            self.add_timeline("VISUAL ANALYSIS","ACTIVE")
            return

        if line.startswith("MEMORY>"):
            self.pulse_module("MEMORY")
            return

        if line.startswith("ULTRON>"):
            txt=line.split(">",1)[1].strip()
            self.task_text.setText(txt)
            if any(x in txt.lower() for x in ["done","finished","opening","created","saved","learned","complete"]):
                self.core.set_state("COMPLETE")
                self.task_status.setText("TASK COMPLETE")
                self.add_timeline("ULTRON RESPONSE","✓ COMPLETE")
            elif "error" in txt.lower() or "couldn't" in txt.lower():
                self.sync_visual_state("ERROR")
                self.task_status.setText("ATTENTION")
            else:
                self.sync_visual_state("ACTIVE")
                self.task_status.setText("READY")
            return

    def refresh_stats(self):
        self.clock.setText(time.strftime("%H:%M:%S"))
        self.cpu.set_value(f"{psutil.cpu_percent(interval=None):.0f}%")
        self.ram.set_value(f"{psutil.virtual_memory().percent:.0f}%")
        try:
            self.disk.set_value(f"{psutil.disk_usage(Path.home().anchor or '/').percent:.0f}%")
        except Exception:
            self.disk.set_value("N/A")
        try:
            self.proc.set_value(str(len(psutil.pids())))
        except Exception:
            self.proc.set_value("N/A")
        try:
            uptime_s=max(0,int(time.time()-psutil.boot_time()))
            hours=uptime_s//3600
            mins=(uptime_s%3600)//60
            self.uptime.set_value(f"{hours}H {mins:02d}M")
        except Exception:
            self.uptime.set_value("N/A")
        bat=psutil.sensors_battery()
        self.battery.set_value(f"{bat.percent:.0f}%" if bat else "N/A")
        self.net.set_value("ONLINE" if self.has_network() else "OFFLINE")
        try:
            from memory import LongTermMemory
            # avoid repeatedly opening DB; only cheap visual stat
        except Exception:
            pass

    def has_network(self):
        stats=psutil.net_if_stats()
        return any(v.isup for v in stats.values())

    def keyPressEvent(self,event):
        if event.key()==Qt.Key_F11:
            if self.isFullScreen():
                self.showNormal()
            else:
                self.showFullScreen()
            return
        if event.key()==Qt.Key_Escape:
            if self.isFullScreen():
                self.showNormal()
            else:
                self.close()
            return
        super().keyPressEvent(event)

    def closeEvent(self,event):
        try:
            self.floating.hide()
        except Exception:
            pass
        if self.process.state()!=QProcess.NotRunning:
            self.process.terminate()
            if not self.process.waitForFinished(1500):
                self.process.kill()
        event.accept()

def main():
    app=QApplication(sys.argv)
    app.setApplicationName("Ultron Interface")
    w=UltronWindow()
    w.showMaximized()
    sys.exit(app.exec())

if __name__=="__main__":
    main()
