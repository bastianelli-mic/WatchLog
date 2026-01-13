package it.bastio.service;

import it.bastio.model.Film;
import jakarta.enterprise.context.ApplicationScoped;

import java.util.ArrayList;
import java.util.List;

@ApplicationScoped
public class FilmService {

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

    public List<Film> getFilms() {
        return films;
    }

    public Film getFilmById(Integer id) {
        return films.get(id);
    }

    public Film addFilm(Film film) {
        films.add(film);
        return film;
    }

    public Film removeFilm(Integer id) {
        Film film = films.get(id);
        films.remove(film);
        return film;
    }
}
