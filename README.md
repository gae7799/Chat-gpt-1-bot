# Beyond The Next — Bot-Foto

Applicazione Windows per gestire il catalogo fotografico Fourthwall, l'analisi OpenAI e i rapporti giornalieri. Include l'aggiornamento automatico all'avvio tramite le release di questa repository.

## Installazione

Scaricare `Aggiornamento-Automatico-2.0.1.zip` dalla release, estrarlo e avviare `INSTALLA_AGGIORNAMENTO.bat`. Selezionare la cartella Bot-Foto già in uso. Chiudere prima il bot e il suo avvio. In seguito usare sempre `AVVIA.bat`.

## Aggiornamenti

`app/avvia_bot.py` è un avvio stabile: legge l'ultima release pubblica, verifica manifesto e hash, accetta solo i nomi di file consentiti, crea backup e una registrazione persistente dell'installazione. Al primo avvio del nuovo programma controlla il segnale di avvio; in caso di errore ripristina il codice precedente e blocca quella versione. Le interruzioni di alimentazione vengono gestite al successivo avvio. Due istanze non possono aggiornare contemporaneamente la cartella.

Il programma già aperto non viene interrotto per aggiornarsi. Il controllo avviene al successivo avvio; l'assenza di rete permette di usare la versione installata. L'integrità è verificata con SHA-256; la fonte delle release è l'account GitHub autorizzato tramite HTTPS. Non vengono eseguiti script di installazione scaricati.

Foto, credenziali e database restano sul PC e non fanno parte dei pacchetti. Il rollback copre il codice; le migrazioni dati future devono essere additive e compatibili con la versione precedente. Nessuna pubblicazione Fourthwall già avvenuta viene annullata dal rollback.

## Pubblicare una versione

1. Modificare i sorgenti in `app/` e incrementare `app/VERSION.txt` con tre numeri, per esempio `2.0.2`.
2. Aggiornare i test. Per nuovi moduli verificare la compatibilità con l'elenco dei file accettati dal programma di avvio già distribuito.
3. Eseguire `PYTHONPATH=app python -m unittest discover -s tests -v` (su Windows impostare PYTHONPATH secondo la shell).
4. Eseguire `python tools/build_release.py` per produrre i pacchetti in `dist/`.
5. Pubblicare un tag `v2.0.2`, oppure avviare manualmente il workflow **Verifica e pubblica aggiornamento** in Actions.

Il workflow verifica su Windows e Linux e crea la release solo dopo il successo dei test. Non sovrascrive una release già esistente: usare sempre una versione nuova. Una modifica su main senza release non viene distribuita automaticamente.

Il manifesto e lo ZIP devono essere allegati alla stessa release stabile, con tag corrispondente alla versione. Non mettere nelle release file FOTO, DATI, credenziali o backup.

## Limiti attuali

La ricerca di mercato e l'analisi delle immagini usano l'API OpenAI a consumo. Le proposte editoriali giornaliere sono consultive; il calendario gestisce le opere già approvate. Visite, ordini, vendite e calcolo automatico dei prezzi dai costi effettivi non sono ancora integrati. Budget pubblicitario: 0 euro.

## Riferimenti

- [GitHub Releases API](https://docs.github.com/en/rest/releases/releases)
- [OpenAI Web Search](https://developers.openai.com/api/docs/guides/tools-web-search)
