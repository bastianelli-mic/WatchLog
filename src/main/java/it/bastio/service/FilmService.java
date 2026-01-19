package it.bastio.service;

import io.smallrye.mutiny.Uni;
import it.bastio.model.Film;
import jakarta.enterprise.context.ApplicationScoped;
import jakarta.inject.Inject;
import org.hibernate.reactive.mutiny.Mutiny;

import java.util.ArrayList;
import java.util.List;

@ApplicationScoped
public class FilmService {

    @Inject
    Mutiny.SessionFactory sf;

    private List<Film> films = new ArrayList<>();

    public FilmService() {
        var dickEJane = Film.builder()
                .title("Dick & Jane - Operazione furto")
                .year(2005)
                .duration(91)
                .build();

        var lego = Film.builder()
                .title("The Lego Movie")
                .year(2014)
                .duration(101)
                .build();

        var streghe =  Film.builder()
                .title("Le streghe")
                .year(2020)
                .duration(106)
                .build();

        films.add(dickEJane);
        films.add(lego);
        films.add(streghe);
    }

    public Uni<List<Film>> getFilms() {
        return Uni.createFrom().item(films);
    }

    public Uni<Film> getFilmById(Integer id) {
        return Uni.createFrom().item(films.get(id));
    }

    public Uni<Film> addFilm(Film film) {
        return sf.withTransaction(session -> session.persist(film))
            .map(unused -> film);
    }

    public Uni<Film> patchFilm(Integer id, Film film, boolean patch) {
        films.set(id, film);
        return Uni.createFrom().item(film);
    }

    public Uni<Film> removeFilm(Integer id) {
        Film film = films.get(id);
        films.remove(film);
        return Uni.createFrom().item(film);
    }
}
