# Beyond The Next — Bot-Foto

Applicazione Windows per gestire il catalogo fotografico Fourthwall, l'analisi OpenAI e i rapporti giornalieri. Include l'aggiornamento automatico all'avvio tramite le release di questa repository.

## Installazione

Scaricare `AGGIORNA_E_AVVIA.bat` dalla release 2.1.2, copiarlo nella cartella Bot-Foto già in uso e aprirlo con il bot chiuso. Il BAT scarica il pacchetto della versione, verifica SHA-256, installa nella stessa cartella e avvia il bot. In seguito usare sempre `AVVIA.bat`, che controlla le nuove release all’avvio. In alternativa scaricare lo ZIP completo e usare `INSTALLA_AGGIORNAMENTO.bat`.

## Aggiornamenti

`app/avvia_bot.py` è un avvio stabile: legge l'ultima release pubblica, verifica manifesto e hash, accetta solo i nomi di file consentiti, crea backup e una registrazione persistente dell'installazione. Al primo avvio del nuovo programma controlla il segnale di avvio; in caso di errore ripristina il codice precedente e blocca quella versione. Le interruzioni di alimentazione vengono gestite al successivo avvio. Due istanze non possono aggiornare contemporaneamente la cartella.

Il programma già aperto non viene interrotto per aggiornarsi. Il controllo avviene al successivo avvio; l'assenza di rete permette di usare la versione installata. L'integrità è verificata con SHA-256; la fonte delle release è l'account GitHub autorizzato tramite HTTPS. Non vengono eseguiti script di installazione scaricati.

Foto, credenziali e database restano sul PC e non fanno parte dei pacchetti. Il rollback copre il codice; le migrazioni dati future devono essere additive e compatibili con la versione precedente. Nessuna pubblicazione Fourthwall già avvenuta viene annullata dal rollback.

## Pubblicare una versione

1. Modificare i sorgenti in `app/` e incrementare `app/VERSION.txt` con tre numeri, per esempio `2.0.7`.
2. Aggiornare i test. Per nuovi moduli verificare la compatibilità con l'elenco dei file accettati dal programma di avvio già distribuito.
3. Eseguire `PYTHONPATH=app python -m unittest discover -s tests -v` (su Windows impostare PYTHONPATH secondo la shell).
4. Eseguire `python tools/build_release.py` per produrre i pacchetti in `dist/`.
5. Pubblicare un tag `v2.0.7`, oppure avviare manualmente il workflow **Verifica e pubblica aggiornamento** in Actions.

Il workflow verifica su Windows e Linux e crea la release solo dopo il successo dei test. Non sovrascrive una release già esistente: usare sempre una versione nuova. Una modifica su main senza release non viene distribuita automaticamente.

Il manifesto e lo ZIP devono essere allegati alla stessa release stabile, con tag corrispondente alla versione. Non mettere nelle release file FOTO, DATI, credenziali o backup.

## Limiti attuali

La ricerca di mercato e l'analisi delle immagini usano l'API OpenAI a consumo. Le proposte editoriali giornaliere sono consultive; il calendario gestisce le opere già approvate. Visite, ordini, vendite e calcolo automatico dei prezzi dai costi effettivi non sono ancora integrati. Budget pubblicitario: 0 euro.

## Riferimenti

- [GitHub Releases API](https://docs.github.com/en/rest/releases/releases)
- [OpenAI Web Search](https://developers.openai.com/api/docs/guides/tools-web-search)

## Registro e specialisti

Durante l’attività il bot controlla FOTO ogni 15 secondi; la coda AI e il calendario ogni minuto, lo shop ogni 5 minuti. Il diario produce un riepilogo fattuale circa ogni minuto (normalmente cinque in cinque minuti, limite 50 in una finestra di cinque minuti). Le azioni reali e gli errori restano nello storico completo; gli errori identici sono aggregati per cinque minuti. I quattro specialisti producono pareri con una singola analisi per foto entro il limite AI di cinque richieste al giorno; i riepiloghi richiamano azioni già registrate, senza nuove chiamate API né valutazioni inventate.

Il diario ha un ciclo separato dalle chiamate a Fourthwall e OpenAI, con riprova breve se il registro è momentaneamente occupato. Ogni voce descrive la lettura dei dati, il risultato, il parere consultato e le ultime azioni effettive senza presentare un riepilogo come nuova analisi AI.

Il registro attività mostra la colonna **Chi** con il componente che ha emesso la voce. Questo campo è presente anche nei TXT e nel JSON; per eventi creati prima della versione 2.0.6 mostra “Origine non registrata”. La prima apertura migra automaticamente il database e riesporta gradualmente i vecchi TXT con tale indicazione.

## Studio marketing continuo

Mettere documenti in formato `.txt` o `.md` con testo UTF-8 nella cartella `DOCUMENTI_MARKETING` accanto a `FOTO` e `DATI`. Il bot crea la cartella da solo e la controlla circa ogni minuto mentre è aperto: fino a 25 documenti e 128 KiB ciascuno. In **Quattro specialisti** premere **Studio marketing e documenti**, oppure premere **Studio marketing** nella finestra principale. I rapporti locali sono in `DATI/RAPPORTI_MARKETING/rapporto-attuale.html`, `.txt` e `.json`; il registro attribuisce ogni aggiornamento effettivo allo **Specialista marketing**. File non leggibili o formati diversi da TXT/MD vengono segnalati come non letti.

Il rapporto contiene estratti dei documenti, eventuali fonti citate nella ricerca di mercato giornaliera, stato del prodotto nel catalogo Fourthwall verificato e i pareri marketing già registrati per ogni foto. I collegamenti tra documento e opera mostrano solo parole specifiche in comune con il titolo, tema e descrizione della foto: sono spunti editoriali, non prove di domanda o vendite. Per foto storiche prive di metadati descrittivi i collegamenti possono mancare. Questa rilettura locale non invia documenti a OpenAI e non effettua nuove chiamate API; la ricerca esterna giornaliera mantiene i propri limiti e il proprio costo a consumo. Non modifica prezzi, non pubblica e non spende in pubblicità (budget 0 €).

## Presidente — versione 2.1.0

Il pulsante **Presidente** apre lo stato del coordinatore, le decisioni e gli incarichi. Con gestione autonoma attiva, il Presidente attende il rapporto giornaliero (oppure una fase fallita che abbia esaurito i due tentativi) e consulta catalogo, pareri dei quattro specialisti, ricerca di mercato, proposta editoriale e ultima decisione. L'analisi usa i testi disponibili: non rivaluta direttamente le immagini. Il contesto inviato è limitato e il rapporto indica le fonti escluse.

- **GPT-6 Sol**: massimo un tentativo per giorno locale, fino a 4.000 token di output, inclusi quelli di ragionamento.
- **GPT-6 Astra**: massimo un tentativo per settimana ISO di calendario, fino a 6.000 token di output, dopo una valutazione quotidiana riuscita.
- Le quote persistono dopo il riavvio e comprendono gli errori. Nessun tentativo a pagamento viene ripetuto nello stesso periodo; un'esecuzione interrotta è segnalata dopo 20 minuti. I periodi sono di calendario: domenica e lunedì appartengono a settimane diverse.
- Queste richieste API sono separate dalle cinque analisi fotografiche giornaliere e dai rapporti giornalieri. Servono credito API e accesso ai modelli con la chiave salvata; un modello non accessibile produce una diagnosi, senza sostituzioni automatiche.
- **Sospendi Presidente** ferma le nuove valutazioni; sospendere la gestione autonoma ferma anche il Presidente. Una richiesta già inviata può terminare.

Ogni decisione include sintesi, dati mancanti e fino a cinque incarichi, con destinatario, fotografia quando pertinente, fonti, motivazione e criterio di completamento. Gli ID di fonti e fotografie sono verificati prima di registrare gli incarichi. Gli incarichi marketing vengono consultati dalla successiva ricerca giornaliera; quelli del direttore dalla successiva proposta editoriale; gli incarichi pertinenti entrano nelle successive analisi fotografiche. **Consultato** indica che un componente ha prodotto un risultato dopo aver letto l'incarico: non certifica che l'azione suggerita sia completata. Le opere storiche non vengono rianalizzate automaticamente per questi incarichi.

Il Presidente produce e distribuisce priorità consultive. Le pubblicazioni continuano tramite il calendario già autorizzato; non è introdotta una nuova funzione per cambiare prezzi o acquistare pubblicità. Budget pubblicitario: 0 €. I documenti grezzi della cartella DOCUMENTI_MARKETING restano locali; il Presidente riceve i rapporti dei servizi e i metadati del catalogo.

Decisioni, contesto e incarichi sono persistenti nel database locale; le ultime 30 valutazioni e gli ultimi 150 incarichi sono esportati in **DATI/PRESIDENTE/rapporto.html**, **rapporto.txt** e **rapporto.json**. Il registro mostra il modello usato, l'inizio, l'esito e gli incarichi consultati. Il database conserva anche lo storico precedente ai limiti dell'esportazione.

## Dialogo con l’agente — versione 2.1.1

Il pulsante **Parla con l’agente** apre una chat. Il bot legge uno stato limitato del catalogo locale, del calendario, del Presidente e gli ultimi eventi non periodici del registro; mantiene la cronologia delle domande e risposte nel database locale e nel file **DATI/CHAT_AGENTE/conversazione.txt**. Invia a OpenAI la domanda, una breve cronologia e quel contesto solo quando premi **Invia**: serve la chiave API, ogni messaggio può costare, e il limite è 20 richieste al giorno. La chat usa GPT-6 Sol e non interviene direttamente su Fourthwall, prezzi o campagne. Le istruzioni contenute nei documenti e nei registri sono trattate come dati. Lo stato `Public` indica visibilità, non disponibilità: per capire perché una stampa appare `Sold Out` occorre verificare disponibilità e varianti in Fourthwall. La colonna **Copie** indica file uguali nella cartella FOTO, non pezzi vendibili.

Ogni cinque minuti il supervisore legge visibilità, stato di vendita e varianti dei prodotti collegati al catalogo. Se una scheda `PUBLIC` è `SOLD_OUT` e le varianti non hanno scorte esplicitamente a zero, prova a renderla disponibile e verifica con una seconda lettura. Quando Fourthwall segnala una variante esaurita, registra il problema senza inventare scorte. Una vecchia scheda pubblica collegata alla stessa foto viene nascosta solo quando la scheda attiva è già pubblica. Prima di creare una bozza il bot consulta l'intero catalogo del negozio e blocca i titoli identici; se non conosce l'esito della creazione, sospende i tentativi per evitare doppioni. Prima di pubblicare blocca una seconda scheda pubblica con lo stesso titolo. Il registro segnala i casi dubbi da controllare.
