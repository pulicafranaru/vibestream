/* Fixed per genre so it matches everywhere; iOS mirrors this table in GenreColor.swift. */
const COLOURS = {
  Action: [240, 68, 44],
  Adventure: [227, 155, 45],
  'Action & Adventure': [238, 107, 43],
  Comedy: [242, 195, 53],
  Drama: [176, 58, 98],
  Romance: [228, 108, 140],
  Horror: [176, 18, 30],
  Thriller: [154, 184, 58],
  Crime: [79, 125, 179],
  Mystery: [42, 140, 140],
  'Science Fiction': [47, 155, 235],
  Fantasy: [122, 91, 224],
  'Sci-Fi & Fantasy': [78, 125, 235],
  Animation: [181, 101, 232],
  Family: [242, 148, 107],
  Kids: [46, 196, 201],
  Documentary: [79, 163, 143],
  History: [176, 125, 78],
  War: [124, 132, 64],
  'War & Politics': [124, 132, 64],
  Western: [184, 90, 51],
  Music: [227, 72, 156],
  Reality: [255, 123, 92],
  News: [94, 127, 168],
  Talk: [217, 170, 75],
  Soap: [192, 138, 216],
}
const NEUTRAL = [142, 138, 134]

export function genreRGB(name) {
  return (COLOURS[name] || NEUTRAL).join(', ')
}
