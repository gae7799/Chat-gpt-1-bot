"""Persistent local Fourthwall connection; Windows Credential Manager."""
import ctypes as C
from ctypes import wintypes as W
import os
import queue
import threading
from collega_fourthwall import read_endpoint
TARGET = 'BotFoto/Fourthwall/API'

class Credential(C.Structure):
    _fields_ = [('Flags', W.DWORD), ('Type', W.DWORD), ('TargetName', W.LPWSTR),
      ('Comment', W.LPWSTR), ('LastWritten', W.FILETIME), ('CredentialBlobSize', W.DWORD),
      ('CredentialBlob', C.POINTER(C.c_ubyte)), ('Persist', W.DWORD),
      ('AttributeCount', W.DWORD), ('Attributes', C.c_void_p),
      ('TargetAlias', W.LPWSTR), ('UserName', W.LPWSTR)]

class Vault:
    def __init__(self, target=TARGET):
        if os.name != 'nt': raise RuntimeError('Richiede Windows.')
        self.target = target
        self.api = C.WinDLL('Advapi32.dll', use_last_error=True)
        self.api.CredWriteW.argtypes = [C.POINTER(Credential), W.DWORD]
        self.api.CredWriteW.restype = W.BOOL
        self.api.CredReadW.argtypes = [W.LPCWSTR, W.DWORD, W.DWORD, C.POINTER(C.POINTER(Credential))]
        self.api.CredReadW.restype = W.BOOL
        self.api.CredDeleteW.argtypes = [W.LPCWSTR, W.DWORD, W.DWORD]
        self.api.CredDeleteW.restype = W.BOOL
        self.api.CredFree.argtypes = [C.c_void_p]
        self.api.CredFree.restype = None

    def save(self, username, password):
        data = password.encode('utf-16-le')
        if len(data) > 2560: raise ValueError('Password troppo lunga.')
        blob = (C.c_ubyte * len(data)).from_buffer_copy(data)
        cred = Credential()
        cred.Type, cred.TargetName, cred.UserName = 1, self.target, username
        cred.CredentialBlobSize, cred.CredentialBlob = len(data), blob
        cred.Persist = 2  # Local machine, current Windows user; survives logout.
        try:
            if not self.api.CredWriteW(C.byref(cred), 0):
                raise RuntimeError('Windows non ha salvato le credenziali.')
        finally:
            C.memset(blob, 0, len(data))

    def load(self):
        ptr = C.POINTER(Credential)()
        if not self.api.CredReadW(self.target, 1, 0, C.byref(ptr)):
            if C.get_last_error() == 1168: return None
            raise RuntimeError('Impossibile leggere le credenziali Windows.')
        try:
            cred = ptr.contents
            return cred.UserName, C.string_at(cred.CredentialBlob, cred.CredentialBlobSize).decode('utf-16-le')
        finally:
            if ptr.contents.CredentialBlobSize:
                C.memset(ptr.contents.CredentialBlob, 0, ptr.contents.CredentialBlobSize)
            self.api.CredFree(ptr)

    def delete(self):
        if not self.api.CredDeleteW(self.target, 1, 0) and C.get_last_error() != 1168:
            raise RuntimeError('Impossibile rimuovere le credenziali Windows.')


def verify_and_save(user, password, vault, reader=read_endpoint):
    if not user or not password or ':' in user or any(c in user + password for c in '\r\n\x00'):
        return False, 'Inserisci username e password API validi.'
    result = reader('/shops/current', user, password)
    if not result['ok']: return False, result['message']
    vault.save(user, password)
    return True, 'Collegato a Fourthwall. Credenziali salvate in Windows.'


def mount(parent, root):
    import tkinter as tk
    from tkinter import ttk, messagebox
    panel = ttk.LabelFrame(parent, text='Fourthwall - collegamento API', padding=10)
    panel.pack(fill='x', pady=8)
    state = tk.StringVar(value='Controllo delle credenziali salvate...')
    ttk.Label(panel, textvariable=state, wraplength=820).pack(anchor='w')
    ttk.Label(panel, text='Accesso del programma sul PC. Non collega questa chat al negozio.').pack(anchor='w')
    actions = ttk.Frame(panel)
    actions.pack(anchor='w', pady=6)
    result_queue = queue.Queue()
    busy = [False]
    buttons = []
    dialog = [None]

    def launch(fn):
        if busy[0]: return
        busy[0] = True
        for b in buttons: b.configure(state='disabled')
        state.set('Verifica in corso...')
        def worker():
            try: result_queue.put(fn())
            except Exception: result_queue.put((False, 'Operazione non riuscita. Controlla Windows e riprova; nessuna credenziale mostrata.'))
        threading.Thread(target=worker, daemon=True).start()

    def reconnect():
        def run():
            pair = Vault().load()
            if not pair: return False, 'Da configurare: premi Collega e salva.'
            res = read_endpoint('/shops/current', *pair)
            return res['ok'], ('Collegato a Fourthwall (verifica di lettura riuscita).' if res['ok'] else res['message'])
        launch(run)

    def configure():
        if dialog[0] and dialog[0].winfo_exists():
            dialog[0].lift()
            return
        win = tk.Toplevel(root)
        dialog[0] = win
        win.title('Collega Fourthwall')
        win.geometry('550x310')
        body = ttk.Frame(win, padding=18)
        body.pack(fill='both', expand=True)
        ttk.Label(body, text='Usa username e password Open API, non il login Google.').pack(anchor='w')
        ttk.Label(body, text='Username API').pack(anchor='w', pady=(12, 3))
        user = ttk.Entry(body, show='*'); user.pack(fill='x')
        ttk.Label(body, text='Password API').pack(anchor='w', pady=(8, 3))
        secret = ttk.Entry(body, show='*'); secret.pack(fill='x')
        ttk.Label(body, text='Premendo il pulsante, verifichi e salvi le credenziali nella\nGestione credenziali del tuo utente Windows su questo PC.').pack(anchor='w', pady=12)
        def save():
            u, p = user.get().strip(), secret.get()
            if not u or not p:
                messagebox.showerror('Dati mancanti', 'Compila entrambi i campi.', parent=win)
                return
            user.delete(0,'end'); secret.delete(0,'end'); win.destroy()
            launch(lambda: verify_and_save(u, p, Vault()))
        ttk.Button(body, text='Verifica e salva sul PC', command=save).pack(anchor='w')

    def forget():
        try:
            Vault().delete()
            state.set('Scollegato. Credenziali rimosse da questo utente Windows.')
        except Exception:
            state.set('Rimozione non riuscita. Riprova dalla Gestione credenziali Windows.')

    for text, command in [('Collega e salva',configure), ('Verifica ora',reconnect), ('Scollega',forget)]:
        b = ttk.Button(actions, text=text, command=command)
        b.pack(side='left', padx=(0,8)); buttons.append(b)
    def poll():
        try:
            ok, message = result_queue.get_nowait()
            state.set(message)
            busy[0] = False
            for b in buttons: b.configure(state='normal')
        except queue.Empty: pass
        root.after(200, poll)
    def periodic():
        if not busy[0] and not (dialog[0] and dialog[0].winfo_exists()): reconnect()
        root.after(300000, periodic)
    root.after(200, poll)
    root.after(500, periodic)
