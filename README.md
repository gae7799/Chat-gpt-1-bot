# Beyond The Next — Bot-Foto

Applicazione Windows per gestire il catalogo fotografico Fourthwall, l'analisi OpenAI e i rapporti giornalieri. Include l'aggiornamento automatico all'avvio tramite le release di questa repository.

## Installazione

Scaricare `AGGIORNA_E_AVVIA.bat` dalla release 2.0.6, copiarlo nella cartella Bot-Foto già in uso e aprirlo con il bot chiuso. Il BAT scarica il pacchetto della versione, verifica SHA-256, installa nella stessa cartella e avvia il bot. In seguito usare sempre `AVVIA.bat`, che controlla le nuove release all’avvio. In alternativa scaricare lo ZIP completo e usare `INSTALLA_AGGIORNAMENTO.bat`.

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
