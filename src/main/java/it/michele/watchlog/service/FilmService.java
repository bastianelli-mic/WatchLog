package it.michele.watchlog.service;

import io.smallrye.mutiny.Uni;
import it.michele.watchlog.model.Film;
import jakarta.enterprise.context.ApplicationScoped;
import jakarta.inject.Inject;
import org.hibernate.reactive.mutiny.Mutiny;

@ApplicationScoped
public class FilmService {

    @Inject
    Mutiny.SessionFactory sf;

    public Uni<Void> create(Film film) {
        return sf.withTransaction(
                session -> session.persist(film)
        );
    }

    public Uni<Void> create(String title) {
        var film = new Film();
        film.setTitle(title);

        return sf.withTransaction(
                session -> session.persist(film)
        );
    }

    public Uni<Film> findById(long id){
        return sf.withTransaction(
                session -> session.find(Film.class, id)
        );
    }
}
